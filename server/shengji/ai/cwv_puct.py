"""PUCT over sampled worlds with the complete-world evaluator (bridge 2b).

The one-ply bot (``cwv_policy.CWVOnePlyBot``) prices every ballot action by
the complete-world net one ply deep.  This bot spends the same evaluator on
MORE positions per decision: deeper continuations of the promising actions,
fewer of the hopeless ones (Jerry: "we need to be able to try more
positions"; compute is a budget, not a gate).  Design: cwv_puct_design.md.

Tree.  An information-set tree keyed by the PUBLIC action sequence from the
root: a node is the sequence of engine-accepted plays since the root
decision, so one node aggregates statistics over every sampled world in
which that public sequence occurred.  Every node stores ``N`` (visits) and
``W`` (summed leaf values, ROOT seat's team perspective, signed level) and a
child map keyed by the canonical play; ``Q = W / N``.

Worlds.  A pool of ``CWV_WORLD_POOL`` complete worlds is sampled ONCE per
decision through production's sampler (``cwv_policy.sample_worlds``:
``MCBot._sample_hands`` + ``_complete_determinized_hands``, canonicalised);
simulation ``i`` descends in world ``i % pool``.

One simulation.  From the root, choose among the children LEGAL IN THIS
WORLD (a node's children are the union over worlds of production's ballot
``_candidates`` for the seat to act; actions the current world's ballot does
not offer are masked) by

    argmax_a  sigma(s) * Q(s,a) + c_puct * P(s,a) * sqrt(N(s)) / (1 + N(s,a))

where ``sigma(s)`` is +1 when the seat to act is on the root's team and -1
for an opponent (opponents minimise the root's value; values are never
sign-flipped in storage) and an unvisited child takes its parent's ``Q``
(first-play urgency).  Moves are applied in the cloned world (engine truth,
``_trusted_rollout``).  The first unvisited child ends the descent: the
reached position is the leaf, its node is created and expanded (its ballot
in this world becomes its child map), and the position is handed to the
evaluator from the root seat's perspective (terminal positions exact).
Backup adds the leaf value to ``W`` and 1 to ``N`` of every node on the
path.

Prior.  ``P(s,a)`` is the public prior head (a ``shengji-train-v0`` checkpoint
trained on the search's final move) softmaxed over the node's ballot for the
seat to act -- ``prior="head"`` -- or uniform (``prior="uniform"``, the
control that isolates the tree from the prior).  Priors are cached per
(node, action): a world whose ballot introduces actions the node has not
seen queues a prior request that is served in the next batched step; until
then the newcomer takes the node's mean prior.  Optional Dirichlet noise at
the root (off by default).  ``prior="value"`` prices the ballot by the
complete-world net itself: the one-ply afterstate of every ballot action
(``cwv_policy.child_position``, the two-ply / net-rollout ballot) is scored
in ONE ``score_many`` from the ACTING seat's team perspective (the seat
maximises its own team, as ``net_rollout._net_perspective``) and the prior
is ``softmax(values / prior_temperature)`` (``value_prior``; the
temperature is on the level scale, default 1).  With ``leaf="playout"``
this is the arm in which the net's ranking guides a tree whose values are
production's playouts.

Batching.  ``CWV_BATCH`` (K) simulations are descended together under
VIRTUAL LOSS -- a pending path adds one pending visit to each of its nodes,
priced as ``-vloss`` from the selecting seat's view -- their leaves are
scored in ONE ``score`` call, then every path is backed up and its pending
visits removed.  Budget = ``CWV_SIMULATIONS`` (S) per decision; move =
argmax root visits (temperature 0; ties by ``Q``, then ballot order).

Leaf.  ``leaf="net"`` (default) hands the leaf position to the evaluator.
``leaf="playout"`` values the leaf by production's own continuation
instead: a HEURISTIC PLAYOUT of the sampled world from the leaf to round
end (``MCBot._rollout``'s loop -- ``rollout_policy`` (HeuristicBot) plays
every seat, the S3b exact-endgame hook applies when ``EXACT_ENDGAME`` is
on and the world is inside the proved bound), converted EXPLICITLY from
production's attacker-points scale to the tree's signed-level scale
(``playout_level``: ``attacker_level_utility`` signed from the root seat's
team, the same map ``terminal_distribution`` applies to a terminal leaf).
``leaf_playouts`` averages several playouts per leaf.  The net (or the
prior table) is then only the prior.

The no-learning control is the same tree with a uniform prior and the
stratified-prior table (``StratifiedPriorEvaluator``, PT0 units as in the
one-ply control) at the leaf (under ``leaf="playout"``: the same playout
leaf, i.e. no learned component at all).  Declare and bury stay production's.
"""

from __future__ import annotations

import copy
import math
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..engine.combos import decompose
from ..engine.round import Round, Trick, TrickPlay
from ..rl.value_afterstate import category_signed_level, signed_level_category
from .cwv_policy import (
    CWVError,
    StratifiedPriorEvaluator,
    checkpoint_id,
    child_position,
    file_sha256,
    prior_evaluator_for,
    sample_worlds,
    shared_evaluator,
)
from .mcbot import MCBot, _ballot_identity, _runtime_identity
from .memory import Memory


CWV_PUCT_DECISION_SCHEMA = "cwv-puct-decision-v1"
PRIOR_MODES = ("uniform", "head", "value")
DEFAULT_PRIOR_TEMPERATURE = 1.0
LEAF_MODES = ("net", "playout")
DEFAULT_WORLD_POOL = 32
DEFAULT_BATCH = 16
DEFAULT_C_PUCT = 1.5
DEFAULT_VIRTUAL_LOSS = 1.0


def action_key(cards: Sequence[str]) -> tuple[str, ...]:
    """A play's canonical identity (a multiset of card codes)."""
    return tuple(sorted(cards))


# ----------------------------------------------------------------- the tree

class Edge:
    """Statistics of one ATTEMPTED action at a node (what PUCT selects and
    what the root's visit counts are read from)."""

    __slots__ = ("N", "W", "pending")

    def __init__(self):
        self.N = 0
        self.W = 0.0
        self.pending = 0

    @property
    def Q(self) -> float:
        return self.W / self.N if self.N else 0.0


class Node:
    """One public state below the root: statistics, edges, children, prior.

    ``N``/``W``: completed visits and their summed root-team values.
    ``pending``: paths in flight under virtual loss (removed at backup).
    ``seat``: the seat to act here (``None`` at a terminal).  ``actions``:
    the union over worlds of the ballots seen here, in first-seen order;
    ``prior``: ``{action: P}`` for the priced ones.  ``edges``: per ATTEMPTED
    action, the statistics PUCT selects on.  ``children``: child states keyed
    by the ACCEPTED public transition -- the play the engine resolved after
    ``clone.play`` -- because a throw the engine refuses in one world becomes
    a forced play with another public outcome, and the two must not share a
    state node (Codex, PR #233).
    """

    __slots__ = ("N", "W", "pending", "seat", "actions", "prior", "edges", "children",
                 "terminal", "depth", "key", "world_ballots")

    def __init__(self, key: tuple, depth: int):
        self.key = key
        self.depth = depth
        self.N = 0
        self.W = 0.0
        self.pending = 0
        self.seat: int | None = None
        self.actions: list[tuple[str, ...]] = []
        self.prior: dict[tuple[str, ...], float] = {}
        self.edges: dict[tuple[str, ...], Edge] = {}
        self.children: dict[tuple[str, ...], Node] = {}
        self.terminal = False
        #: this node's ballot per world index (deterministic per world)
        self.world_ballots: dict[int, list[tuple[str, ...]]] = {}

    @property
    def Q(self) -> float:
        return self.W / self.N if self.N else 0.0

    def mean_prior(self) -> float:
        return (sum(self.prior.values()) / len(self.prior)) if self.prior else 1.0

    def edge(self, action: tuple[str, ...]) -> Edge:
        edge = self.edges.get(action)
        if edge is None:
            edge = self.edges[action] = Edge()
        return edge

    def child(self, accepted: tuple[str, ...]) -> "Node":
        """The child state reached by the ACCEPTED play ``accepted``."""
        node = self.children.get(accepted)
        if node is None:
            node = Node(self.key + (accepted,), self.depth + 1)
            self.children[accepted] = node
        return node


def puct_scores(parent_n: int, children: Sequence[tuple[int, float, int]],
                priors: Sequence[float], *, c_puct: float, sign: float,
                fpu_q: float, virtual_loss: float) -> list[float]:
    """The selection scores of a node's legal children (pure, for witnesses).

    ``children`` rows are ``(N, W, pending)`` per child; ``parent_n`` is the
    parent's visits INCLUDING its pending paths.  A child's effective visits
    are ``N + pending`` and its effective value ``(W - sign * vloss *
    pending) / (N + pending)`` -- the pending paths look ``vloss`` worse to
    the selecting seat -- or ``fpu_q`` (the parent's ``Q``) when unvisited.
    Score = ``sign * q + c_puct * P * sqrt(parent_n) / (1 + n)``.
    """
    if len(children) != len(priors):
        raise CWVError("puct_scores: one prior per child")
    root = math.sqrt(max(parent_n, 0))
    scores = []
    for (n, w, pending), p in zip(children, priors):
        total = n + pending
        if total > 0:
            q = (w - sign * virtual_loss * pending) / total
        else:
            q = fpu_q
        scores.append(sign * q + c_puct * float(p) * root / (1.0 + total))
    return scores


def select_move(root: Node, candidates: Sequence[Sequence[str]]) -> int:
    """Argmax ROOT VISITS over the ballot; ties by ``Q``, then ballot order."""
    best = 0
    best_key = None
    for index, cand in enumerate(candidates):
        edge = root.edges.get(action_key(cand))
        n = edge.N if edge is not None else 0
        q = edge.Q if edge is not None and edge.N else float("-inf")
        key = (n, q)
        if best_key is None or key > best_key:
            best, best_key = index, key
    return best


def backup(path: Sequence[Node], value: float, edges: Sequence[Edge] = ()) -> None:
    """Add ``value`` (root-team perspective) to EVERY node on the path (and
    every attempted-action edge taken), increment visits and release the
    path's pending virtual loss."""
    for stat in (*path, *edges):
        stat.N += 1
        stat.W += value
        if stat.pending > 0:
            stat.pending -= 1


# ------------------------------------------------------------ prior head

class PublicPriorHead:
    """The #213 public policy head (``shengji-train-v0`` checkpoint) as a
    prior over a ballot: ``probabilities(rnd, seat, ballot)`` is the softmax
    of the head's logits over exactly that ballot (zero elsewhere).  The
    observation is ``rl.encode.encode_obs`` -- public information plus the
    acting seat's hand in the world it is asked about."""

    def __init__(self, checkpoint: str | os.PathLike[str], *, model=None,
                 metadata: Mapping[str, Any] | None = None):
        import torch

        if model is None:
            from ..train.train_v0 import load_checkpoint
            model, payload = load_checkpoint(checkpoint, torch.device("cpu"))
            metadata = payload
            self.checkpoint_sha256 = file_sha256(checkpoint)
        else:
            self.checkpoint_sha256 = None
        self.checkpoint_path = None if checkpoint is None else str(checkpoint)
        self.model = model
        if hasattr(self.model, "eval"):
            self.model.eval()
        for parameter in getattr(self.model, "parameters", lambda: [])():
            parameter.requires_grad_(False)
        self.metadata = dict(metadata or {})
        self.forward_calls = 0
        self.rows = 0
        self.wall_secs = 0.0

    @property
    def ckpt8(self) -> str | None:
        return None if self.checkpoint_sha256 is None else self.checkpoint_sha256[:8]

    def identity(self) -> dict[str, Any]:
        config = self.metadata.get("config") or {}
        return {"kind": "public_prior_head", "checkpoint": self.checkpoint_path,
                "checkpoint_sha256": self.checkpoint_sha256, "ckpt8": self.ckpt8,
                "prior_target": config.get("prior_target"),
                "schema": self.metadata.get("schema")}

    @staticmethod
    def encode(rnd: Round, seat: int, ballot: Sequence[Sequence[str]]
               ) -> tuple[np.ndarray, np.ndarray]:
        """``(obs, cand)`` rows of one request, encoded NOW (the world clone
        keeps moving; nothing of it is retained)."""
        from ..rl.encode import ACT_DIM, encode_action, encode_obs

        if not ballot:
            raise CWVError("prior head received an empty ballot")
        obs = np.asarray(encode_obs(rnd, seat), dtype=np.float32)
        cand = np.asarray([encode_action(list(play), rnd) for play in ballot],
                          dtype=np.float32).reshape(len(ballot), ACT_DIM)
        return obs, cand

    def batch_probabilities(self, requests: Sequence[tuple[Round, int, Sequence[Sequence[str]]]]
                            ) -> list[np.ndarray]:
        """One forward for many ``(rnd, seat, ballot)`` requests (padded)."""
        return self.batch_from_encoded([self.encode(rnd, seat, ballot)
                                        for rnd, seat, ballot in requests])

    def batch_from_encoded(self, rows: Sequence[tuple[np.ndarray, np.ndarray]]
                           ) -> list[np.ndarray]:
        """One forward for many encoded ``(obs, cand)`` rows (padded)."""
        import torch
        from ..rl.encode import ACT_DIM

        if not rows:
            return []
        wall0 = time.perf_counter()
        width = max(len(cand_rows) for _, cand_rows in rows)
        obs = np.stack([o for o, _ in rows]).astype(np.float32)
        cand = np.zeros((len(rows), width, ACT_DIM), dtype=np.float32)
        mask = np.zeros((len(rows), width), dtype=np.bool_)
        for row, (_o, cand_rows) in enumerate(rows):
            cand[row, :len(cand_rows)] = cand_rows
            mask[row, :len(cand_rows)] = True
        with torch.inference_mode():
            out = self.model(torch.from_numpy(obs), torch.from_numpy(cand),
                             torch.from_numpy(mask))
            logits = out.logits if hasattr(out, "logits") else out[2]
            probs = torch.softmax(logits, dim=1).double().cpu().numpy()
        self.forward_calls += 1
        self.rows += len(rows)
        self.wall_secs += time.perf_counter() - wall0
        result = []
        for row, (_o, cand_rows) in enumerate(rows):
            p = probs[row, :len(cand_rows)]
            if not np.all(np.isfinite(p)) or abs(float(p.sum()) - 1.0) > 1e-5:
                raise CWVError("prior head probability drift")
            result.append(p)
        return result

    def probabilities(self, rnd: Round, seat: int, ballot: Sequence[Sequence[str]]
                      ) -> np.ndarray:
        return self.batch_probabilities([(rnd, seat, ballot)])[0]


@lru_cache(maxsize=4)
def _shared_prior_head(path: str, mtime_ns: int, size: int) -> PublicPriorHead:
    del mtime_ns, size
    return PublicPriorHead(path)


def shared_prior_head(checkpoint: str | os.PathLike[str]) -> PublicPriorHead:
    resolved = Path(checkpoint).resolve()
    if not resolved.is_file():
        raise CWVError(f"prior checkpoint not found: {resolved}")
    stat = resolved.stat()
    return _shared_prior_head(str(resolved), stat.st_mtime_ns, stat.st_size)


# ------------------------------------------------------------- world clone

def world_clone(rnd: Round, hands: Sequence[Sequence[str]], buried: Sequence[str]) -> Round:
    """Clone the root exactly as ``MCBot._rollout`` does, without playing."""
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
    return clone


def playout_level(attacker_points: int | float, root_is_attacker: bool) -> float:
    """Production's playout outcome (final ATTACKER POINTS, what
    ``MCBot._rollout`` and ``_exact_endgame_value`` return) on the tree's
    scale: the SIGNED LEVEL from the root seat's team, exactly the value a
    terminal leaf takes under ``leaf="net"`` (``terminal_distribution @
    support`` = ``category_signed_level(signed_level_category(...))``)."""
    points = float(attacker_points)
    if not points.is_integer():
        raise CWVError("a playout outcome must be an integer attacker-point total")
    return category_signed_level(signed_level_category(int(points), bool(root_is_attacker)))


def leaf_copy(leaf: Round) -> Round:
    """A private continuation copy of a reached leaf (the leaf itself stays
    as reached, for traces and for further playouts)."""
    clone: Round = copy.copy(leaf)
    clone.hands = [list(hand) for hand in leaf.hands]
    clone.buried = list(leaf.buried)
    if leaf.trick is not None:
        clone.trick = Trick(
            leader=leaf.trick.leader,
            plays=[TrickPlay(p.seat, list(p.cards)) for p in leaf.trick.plays])
    clone.history = list(leaf.history)
    clone.message = None
    return clone


def value_prior(values: Sequence[float], temperature: float) -> np.ndarray:
    """``softmax(values / temperature)`` over a ballot (pure, for witnesses).
    ``values`` are signed levels from the acting seat's team perspective."""
    t = float(temperature)
    if not (t > 0.0) or not math.isfinite(t):
        raise CWVError("prior temperature must be a positive finite number")
    v = np.asarray(values, dtype=np.float64)
    if v.ndim != 1 or v.size == 0 or not np.all(np.isfinite(v)):
        raise CWVError("value prior needs a finite non-empty value vector")
    z = v / t
    z = np.exp(z - z.max())
    return z / z.sum()


def prior_identity(prior: str, prior_temperature: float) -> dict[str, Any]:
    """The prior's identity keys beyond ``prior`` itself: ``uniform`` and
    ``head`` add nothing (the v1 record / binding, unchanged); ``value``
    binds its temperature."""
    if prior not in PRIOR_MODES:
        raise CWVError(f"prior mode must be one of {PRIOR_MODES}")
    t = float(prior_temperature)
    if not (t > 0.0) or not math.isfinite(t):
        raise CWVError("prior temperature must be a positive finite number")
    if prior != "value":
        return {}
    return {"prior_temperature": t}


def leaf_identity(leaf: str, leaf_playouts: int) -> dict[str, Any]:
    """The leaf's identity keys.  ``net`` is the implicit default of the
    v1 record / calibration binding (no keys: nothing existing changes);
    ``playout`` binds the mode and the playouts per leaf, so a binding or a
    record made under one leaf never matches the other."""
    if leaf not in LEAF_MODES:
        raise CWVError(f"leaf mode must be one of {LEAF_MODES}")
    if int(leaf_playouts) < 1:
        raise CWVError("leaf_playouts must be positive")
    if leaf == "net":
        return {}
    return {"leaf": leaf, "leaf_playouts": int(leaf_playouts)}


# ----------------------------------------------------------------------- bot

class CWVPuctBot(MCBot):
    """PUCT over a pool of sampled worlds, complete-world net at the leaf.

    Subclasses production for its ballot, sampler, declare and bury; only
    ``decide_play`` is replaced.  Production's tractor lock and
    single-candidate early returns are kept (the same decision boundary as
    the one-ply bot).
    """

    CWV_SIMULATIONS = 256          # S: simulations per decision (the budget)
    CWV_WORLD_POOL = DEFAULT_WORLD_POOL   # W: worlds sampled once per decision
    CWV_BATCH = DEFAULT_BATCH      # K: simulations per batched leaf step
    CWV_C_PUCT = DEFAULT_C_PUCT
    CWV_VIRTUAL_LOSS = DEFAULT_VIRTUAL_LOSS
    CWV_PRIOR = "uniform"          # "uniform" | "head" | "value"
    CWV_PRIOR_TEMPERATURE = DEFAULT_PRIOR_TEMPERATURE   # prior="value" softmax
    CWV_LEAF = "net"               # "net" | "playout" (heuristic playout leaf)
    CWV_LEAF_PLAYOUTS = 1          # playouts averaged per leaf (leaf="playout")
    CWV_DIRICHLET_ALPHA = 0.0      # root noise, off by default
    CWV_DIRICHLET_EPSILON = 0.0
    CWV_TRACE = False              # keep a per-simulation trace (witnesses)

    def __init__(self, seed: int | None = None, *, evaluator=None, prior_head=None):
        super().__init__(seed)
        if evaluator is None or not hasattr(evaluator, "score"):
            raise CWVError("CWVPuctBot needs an evaluator with score()")
        if self.CWV_PRIOR not in PRIOR_MODES:
            raise CWVError(f"prior mode must be one of {PRIOR_MODES}")
        if self.CWV_LEAF not in LEAF_MODES:
            raise CWVError(f"leaf mode must be one of {LEAF_MODES}")
        if int(self.CWV_LEAF_PLAYOUTS) < 1:
            raise CWVError("leaf_playouts must be positive")
        if self.CWV_PRIOR == "head" and (
                prior_head is None or not hasattr(prior_head, "batch_from_encoded")
                or not hasattr(prior_head, "encode")):
            raise CWVError("prior='head' needs a prior head with encode() and "
                           "batch_from_encoded()")
        if self.CWV_PRIOR == "value" and not hasattr(evaluator, "score_many"):
            raise CWVError("prior='value' needs an evaluator with score_many()")
        prior_identity(self.CWV_PRIOR, self.CWV_PRIOR_TEMPERATURE)   # validates
        if int(self.CWV_SIMULATIONS) < 1 or int(self.CWV_WORLD_POOL) < 1 \
                or int(self.CWV_BATCH) < 1:
            raise CWVError("simulations, world pool and batch must be positive")
        self.evaluator = evaluator
        self.prior_head = prior_head if self.CWV_PRIOR == "head" else None
        self.positions_evaluated = 0
        self.cwv_decisions = 0
        self.simulations = 0
        self.forward_passes = 0
        self.depth_max_total = 0     # sum over decisions of the max leaf depth
        self.depth_sum = 0           # sum over simulations of the leaf depth
        self.batch_wall_secs = 0.0
        self.batch_cpu_secs = 0.0
        self.build_wall_secs = 0.0
        self.prior_wall_secs = 0.0
        self.sample_wall_secs = 0.0     # world-pool sampling per decision
        self.leaf_playouts = 0          # heuristic playouts run at leaves
        self.exact_leaves = 0           # leaves settled by the exact-endgame hook
        self.last_root: Node | None = None
        self.last_trace: list[dict] | None = None

    # ------------------------------------------------------------ identity
    def search_identity(self) -> dict[str, Any]:
        return {"kind": "puct", "simulations": int(self.CWV_SIMULATIONS),
                "world_pool": int(self.CWV_WORLD_POOL), "batch": int(self.CWV_BATCH),
                "c_puct": float(self.CWV_C_PUCT),
                "virtual_loss": float(self.CWV_VIRTUAL_LOSS),
                "prior": self.CWV_PRIOR,
                "prior_head": (self.prior_head.identity()
                               if self.prior_head is not None
                               and hasattr(self.prior_head, "identity") else None),
                **prior_identity(self.CWV_PRIOR, self.CWV_PRIOR_TEMPERATURE),
                "dirichlet_alpha": float(self.CWV_DIRICHLET_ALPHA),
                "dirichlet_epsilon": float(self.CWV_DIRICHLET_EPSILON),
                **leaf_identity(self.CWV_LEAF, self.CWV_LEAF_PLAYOUTS)}

    # ------------------------------------------------------------ sampling
    def sample_worlds(self, rnd: Round, seat: int, n: int, *, mem=None):
        return sample_worlds(self, rnd, seat, n, mem=mem)

    # --------------------------------------------------------------- tree
    def _sign(self, seat: int, root_seat: int) -> float:
        return 1.0 if seat % 2 == root_seat % 2 else -1.0

    def _ballot(self, clone: Round, seat: int) -> list[tuple[str, ...]]:
        return [action_key(c) for c in self._candidates(clone, seat)]

    def _expand(self, node: Node, clone: Round, prior_requests: list,
                ballot: Sequence[tuple[str, ...]] | None = None) -> None:
        """Set the node's seat and merge this world's ballot into its union.

        New actions under ``prior="head"`` are queued for the next batched
        prior forward; meanwhile they take the node's mean prior.
        """
        if clone.phase != "play":
            node.terminal = True
            node.seat = None
            return
        seat = clone.turn
        assert seat is not None
        node.seat = seat
        if ballot is None:
            ballot = self._ballot(clone, seat)
        new = [a for a in ballot if a not in node.prior]
        if not new:
            return
        for a in new:
            if a not in node.actions:
                node.actions.append(a)
        if self.CWV_PRIOR == "uniform":
            for a in new:
                node.prior[a] = 1.0
            return
        fill = node.mean_prior()
        for a in new:
            node.prior[a] = fill
        if self.CWV_PRIOR == "value":
            # the one-ply afterstates of this world's ballot, priced from the
            # acting seat's team in the next batched score_many
            prior_requests.append((node, ballot, self._afterstates(clone, seat, ballot), seat))
        else:
            prior_requests.append((node, ballot, self.prior_head.encode(
                clone, seat, [list(a) for a in ballot]), None))

    @staticmethod
    def _afterstates(clone: Round, seat: int, ballot: Sequence[tuple[str, ...]]
                     ) -> list[Round]:
        return [child_position(clone, seat, list(a)) for a in ballot]

    def _value_prior_rows(self, requests: Sequence[tuple]) -> list[np.ndarray]:
        """ONE ``score_many`` over every queued afterstate; per request the
        softmax of its block at ``CWV_PRIOR_TEMPERATURE``."""
        positions: list[Round] = []
        seats: list[int] = []
        for _node, _ballot, afterstates, seat in requests:
            positions.extend(afterstates)
            seats.extend([int(seat)] * len(afterstates))
        values = np.asarray(self.evaluator.score_many(positions, seats), dtype=np.float64)
        if values.shape != (len(positions),):
            raise CWVError("evaluator returned a misaligned prior value vector")
        rows = []
        start = 0
        for _node, _ballot, afterstates, _seat in requests:
            rows.append(value_prior(values[start:start + len(afterstates)],
                                    self.CWV_PRIOR_TEMPERATURE))
            start += len(afterstates)
        return rows

    def _serve_prior_requests(self, prior_requests: list) -> None:
        if not prior_requests or self.CWV_PRIOR == "uniform":
            prior_requests.clear()
            return
        wall0 = time.perf_counter()
        if self.CWV_PRIOR == "value":
            probs = self._value_prior_rows(prior_requests)
        else:
            probs = self.prior_head.batch_from_encoded(
                [encoded for _node, _ballot, encoded, _seat in prior_requests])
        for (node, ballot, _encoded, _seat), p in zip(prior_requests, probs):
            for a, value in zip(ballot, p):
                node.prior[a] = float(value)
        self.forward_passes += 1
        self.prior_wall_secs += time.perf_counter() - wall0
        prior_requests.clear()

    # ---------------------------------------------------------- leaf value
    def _playout(self, leaf: Round, root_seat: int, session) -> tuple[float, bool]:
        """One heuristic playout of ``leaf`` (a private copy) to round end:
        ``MCBot._rollout``'s continuation loop, verbatim -- the exact-endgame
        hook first when enabled, else ``rollout_policy`` for every seat --
        with the outcome converted to the tree's scale.  Returns ``(value,
        exact)``."""
        clone = leaf_copy(leaf)
        root_is_attacker = clone.is_attacker(root_seat)
        policy = self.rollout_policy
        _exact_on = self.EXACT_ENDGAME
        while clone.phase == "play":
            exact = (self._exact_endgame_value(clone, session)
                     if _exact_on else None)
            if exact is not None:
                return playout_level(exact, root_is_attacker), True
            s = clone.turn
            assert s is not None
            clone.play(s, policy.decide_play(clone, s))
        return playout_level(clone.attacker_points, root_is_attacker), False

    def _playout_values(self, leaves: Sequence[Round], root_seat: int,
                        sessions: Sequence[Any]) -> tuple[np.ndarray, int, int]:
        """``leaf_playouts`` playouts per leaf, averaged.  Returns ``(values,
        playouts, exact_leaves)``; ``sessions[i]`` is leaf ``i``'s world's
        exact-endgame cache (``None`` when the hook is off)."""
        n = int(self.CWV_LEAF_PLAYOUTS)
        values = np.empty(len(leaves), dtype=np.float64)
        exact_leaves = 0
        for index, (leaf, session) in enumerate(zip(leaves, sessions)):
            total = 0.0
            exact_all = True
            for _ in range(n):
                value, exact = self._playout(leaf, root_seat, session)
                total += value
                exact_all = exact_all and exact
            values[index] = total / n
            if exact_all:
                exact_leaves += 1
        return values, n * len(leaves), exact_leaves

    def _legal_children(self, node: Node, world_ballot: Sequence[tuple[str, ...]]
                        ) -> list[tuple[str, ...]]:
        """The node's actions this world's ballot offers (the legality mask)."""
        offered = set(world_ballot)
        return [a for a in node.actions if a in offered]

    def _select(self, node: Node, legal: Sequence[tuple[str, ...]], root_seat: int,
                root_noise: dict | None) -> tuple[str, ...]:
        assert node.seat is not None
        sign = self._sign(node.seat, root_seat)
        stats = []
        priors = []
        for a in legal:
            edge = node.edges.get(a)
            stats.append((edge.N, edge.W, edge.pending) if edge is not None
                         else (0, 0.0, 0))
            p = node.prior[a]
            if root_noise is not None:
                p = (1.0 - self.CWV_DIRICHLET_EPSILON) * p \
                    + self.CWV_DIRICHLET_EPSILON * root_noise.get(a, 0.0)
            priors.append(p)
        scores = puct_scores(node.N + node.pending, stats, priors,
                             c_puct=float(self.CWV_C_PUCT), sign=sign,
                             fpu_q=node.Q, virtual_loss=float(self.CWV_VIRTUAL_LOSS))
        best = max(range(len(legal)), key=lambda i: scores[i])
        return legal[best]

    @staticmethod
    def accepted_play(clone: Round, seat: int) -> tuple[str, ...]:
        """The play the engine ACCEPTED for ``seat`` in its newest trick (a
        refused throw comes back as the forced component)."""
        trick = clone.trick
        if trick is not None and trick.plays and trick.plays[-1].seat == seat:
            return action_key(trick.plays[-1].cards)
        last = clone.history[-1].plays[-1]
        if last.seat != seat:
            raise CWVError("engine transition drift: the newest play is not the mover's")
        return action_key(last.cards)

    def _simulate(self, root: Node, rnd: Round, root_seat: int, world, world_index: int,
                  prior_requests: list, root_noise: dict | None
                  ) -> tuple[list[Node], Round, dict | None, list[Edge]]:
        """Descend one path under virtual loss; return ``(path, leaf, trace,
        edges)`` -- the state nodes visited and the attempted-action edges
        taken."""
        hands, buried = world
        clone = world_clone(rnd, hands, buried)
        node = root
        path = [root]
        edges: list[Edge] = []
        trace = {"world": world_index, "moves": []} if self.CWV_TRACE else None
        while True:
            if node.terminal or clone.phase != "play":
                node.terminal = True
                break
            if node is root:
                seat = root.seat
                world_ballot = root.actions
            else:
                seat = clone.turn
                world_ballot = node.world_ballots.get(world_index)
                if world_ballot is None:
                    world_ballot = self._ballot(clone, seat)
                    node.world_ballots[world_index] = world_ballot
                if node.seat != seat or any(a not in node.prior for a in world_ballot):
                    self._expand(node, clone, prior_requests, world_ballot)
            legal = self._legal_children(node, world_ballot)
            if not legal:
                raise CWVError("no legal child in this world at a non-terminal node")
            action = self._select(node, legal, root_seat, root_noise if node is root else None)
            edges.append(node.edge(action))
            clone.play(seat, list(action))
            accepted = self.accepted_play(clone, seat)
            if trace is not None:
                trace["moves"].append((node.key, seat, action, tuple(world_ballot), accepted))
            fresh = accepted not in node.children
            child = node.child(accepted)
            path.append(child)
            node = child
            if fresh:
                self._expand(node, clone, prior_requests)
                break
        for visited in (*path, *edges):
            visited.pending += 1
        return path, clone, trace, edges

    def _search(self, rnd: Round, seat: int, candidates: Sequence[Sequence[str]],
                worlds: Sequence) -> tuple[Node, dict]:
        root = Node((), 0)
        root.seat = seat
        root.actions = [action_key(c) for c in candidates]
        if self.CWV_PRIOR == "uniform":
            root.prior = {a: 1.0 for a in root.actions}
        elif self.CWV_PRIOR == "value":
            wall0 = time.perf_counter()
            hands, buried = worlds[0]
            # the root's afterstates in the first sampled world (as every
            # world-dependent prior: the ballot is the root's, post-lock)
            probs = self._value_prior_rows([(root, root.actions, self._afterstates(
                world_clone(rnd, hands, buried), seat, root.actions), seat)])[0]
            root.prior = {a: float(p) for a, p in zip(root.actions, probs)}
            self.forward_passes += 1
            self.prior_wall_secs += time.perf_counter() - wall0
        else:
            probs = self.prior_head.probabilities(rnd, seat, [list(c) for c in candidates])
            root.prior = {a: float(p) for a, p in zip(root.actions, probs)}
            self.forward_passes += 1
        root_noise = None
        if self.CWV_DIRICHLET_EPSILON > 0 and self.CWV_DIRICHLET_ALPHA > 0:
            draws = [self.rng.gammavariate(self.CWV_DIRICHLET_ALPHA, 1.0)
                     for _ in root.actions]
            total = sum(draws) or 1.0
            root_noise = {a: d / total for a, d in zip(root.actions, draws)}
        S, K = int(self.CWV_SIMULATIONS), int(self.CWV_BATCH)
        pool = len(worlds)
        stats = {"simulations": 0, "positions": 0, "forward_passes": 0,
                 "max_depth": 0, "depth_sum": 0, "batch_wall": 0.0,
                 "batch_cpu": 0.0, "build_wall": 0.0, "terminal_leaves": 0,
                 "playouts": 0, "exact_leaves": 0}
        playout_leaf = self.CWV_LEAF == "playout"
        sessions: list[Any] = []
        if playout_leaf and self.EXACT_ENDGAME:
            # one exact cache per determinization, as production's decision
            sessions = [self._new_exact_world_session(rnd, list(buried))
                        for _hands, buried in worlds]
        prior_requests: list = []
        trace: list[dict] = []
        done = 0
        forwards_before = int(getattr(self.evaluator, "forward_calls", 0))
        while done < S:
            batch = min(K, S - done)
            build0 = time.perf_counter()
            paths, leaves, traces, edge_paths, leaf_sessions = [], [], [], [], []
            for i in range(batch):
                index = done + i
                path, leaf, tr, edges = self._simulate(
                    root, rnd, seat, worlds[index % pool], index % pool,
                    prior_requests, root_noise)
                paths.append(path)
                leaves.append(leaf)
                traces.append(tr)
                edge_paths.append(edges)
                leaf_sessions.append(sessions[index % pool] if sessions else None)
            stats["build_wall"] += time.perf_counter() - build0
            wall0, cpu0 = time.perf_counter(), time.process_time()
            if playout_leaf:
                values, playouts, exact_leaves = self._playout_values(
                    leaves, seat, leaf_sessions)
                stats["playouts"] += playouts
                stats["exact_leaves"] += exact_leaves
            else:
                values = np.asarray(self.evaluator.score(leaves, seat), dtype=np.float64)
            stats["batch_wall"] += time.perf_counter() - wall0
            stats["batch_cpu"] += time.process_time() - cpu0
            if values.shape != (batch,):
                raise CWVError("evaluator returned a misaligned value vector")
            self._serve_prior_requests(prior_requests)
            for path, leaf, value, tr, edges in zip(paths, leaves, values, traces, edge_paths):
                backup(path, float(value), edges)
                depth = len(path) - 1
                stats["max_depth"] = max(stats["max_depth"], depth)
                stats["depth_sum"] += depth
                if leaf.phase == "round_end":
                    stats["terminal_leaves"] += 1
                if tr is not None:
                    tr["value"] = float(value)
                    tr["leaf"] = leaf
                    tr["path"] = [n.key for n in path]
                    trace.append(tr)
            done += batch
            stats["positions"] += batch
        stats["simulations"] = done
        stats["forward_passes"] = (int(getattr(self.evaluator, "forward_calls", 0))
                                   - forwards_before)
        if self.CWV_TRACE:
            self.last_trace = trace
        return root, stats

    # ------------------------------------------------------------ decision
    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        assert rnd.trick is not None and rnd.ordering is not None
        self.last_eval = None
        self.last_n_worlds = 0
        self.last_decision_record = None
        self.last_override_stats = None
        self.last_alloc = None
        self.last_root = None
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
        pool = int(self.CWV_WORLD_POOL)
        mem = Memory(rnd, seat, own_kitty=getattr(self, "BANKER_KITTY", True))
        sample0 = time.perf_counter()
        worlds, attempts = self.sample_worlds(rnd, seat, pool, mem=mem)
        sample_wall = time.perf_counter() - sample0
        self.sample_wall_secs += sample_wall
        used = len(worlds)
        self.last_n_worlds = used
        K = len(candidates)
        S = int(self.CWV_SIMULATIONS)
        short = used == 0
        self.last_alloc = {
            "mode": "cwv_puct", "attempts": attempts,
            "attempt_cap": pool * self.SAMPLE_ATTEMPT_FACTOR,
            "attempt_cap_hit": used < pool, "worlds": used,
            "rollouts": 0 if short else S, "decision_rollouts": 0 if short else S,
            "dummy_rollouts": 0, "budget": S, "short": short,
            "survivors": K, "survivor_indices": list(range(K)),
            "n_by_candidate": [0] * K,
        }
        visits = [0] * K
        means = [float("-inf")] * K
        best = 0
        stats = {"simulations": 0, "positions": 0, "forward_passes": 0,
                 "max_depth": 0, "depth_sum": 0, "batch_wall": 0.0,
                 "batch_cpu": 0.0, "build_wall": 0.0, "terminal_leaves": 0,
                 "playouts": 0, "exact_leaves": 0}
        root = None
        if not short:
            root, stats = self._search(rnd, seat, candidates, worlds)
            self.last_root = root
            for index, cand in enumerate(candidates):
                edge = root.edges.get(action_key(cand))
                if edge is not None and edge.N:
                    visits[index] = edge.N
                    means[index] = edge.Q
            best = select_move(root, candidates)
            self.last_alloc["n_by_candidate"] = visits
            self.positions_evaluated += stats["positions"]
            self.simulations += stats["simulations"]
            self.rollouts += stats["simulations"]
            self.forward_passes += stats["forward_passes"]
            self.depth_max_total += stats["max_depth"]
            self.depth_sum += stats["depth_sum"]
            self.batch_wall_secs += stats["batch_wall"]
            self.batch_cpu_secs += stats["batch_cpu"]
            self.build_wall_secs += stats["build_wall"]
            self.leaf_playouts += stats["playouts"]
            self.exact_leaves += stats["exact_leaves"]
        self.last_eval = (candidates, means)
        self.last_decision_record = {
            "schema": CWV_PUCT_DECISION_SCHEMA,
            "policy": getattr(self, "policy_name", type(self).__name__),
            "policy_class": type(self).__name__,
            "code": _runtime_identity(),
            "ballot": _ballot_identity(self),
            "evaluator": self.evaluator.identity()
            if hasattr(self.evaluator, "identity") else repr(self.evaluator),
            "search": self.search_identity(),
            "n_determinizations": pool,
            "margin": 0.0,
            "seed": self.seed,
            "rng_state": pre_rng_state,
            "candidates": [list(c) for c in candidates],
            "means": means,
            "visits": visits,
            "root_prior": ([root.prior[a] for a in root.actions] if root is not None else None),
            "scores": [float(v) for v in visits],
            "n_by_candidate": visits,
            "eligible_indices": list(range(K)),
            "raw_winner_index": best,
            "worlds": used,
            "alloc": self.last_alloc,
            "work": {
                "positions": stats["positions"],
                "simulations": stats["simulations"],
                "forward_passes": stats["forward_passes"],
                "max_depth": stats["max_depth"],
                "mean_depth": (stats["depth_sum"] / stats["simulations"]
                               if stats["simulations"] else 0.0),
                "terminal_leaves": stats["terminal_leaves"],
                "selection_budget": S,
                "selection_rollouts": stats["simulations"],
                "total_budget": S,
                "total_rollouts": stats["simulations"],
                "batch_wall_secs": stats["batch_wall"],
                "batch_cpu_secs": stats["batch_cpu"],
                "build_wall_secs": stats["build_wall"],
                "sample_wall_secs": sample_wall,
                **({"playouts": stats["playouts"],
                    "exact_leaves": stats["exact_leaves"]}
                   if self.CWV_LEAF == "playout" else {}),
            },
        }
        if short:
            self.zero_world_decisions += 1
            self.short_search_decisions += 1
            return self._finish_decision(
                candidates, 0, "selection_underfilled", started, sampler_before)
        return self._finish_decision(
            candidates, best, "puct_argmax_visits" if best != 0 else "candidate0_best",
            started, sampler_before)


# ------------------------------------------------------------- registry glue

def prior_suffix(prior: str = "uniform",
                 prior_temperature: float = DEFAULT_PRIOR_TEMPERATURE) -> str:
    """``""`` for uniform / head; ``-vprior`` / ``-vprior<T>`` for the value prior."""
    if not prior_identity(prior, prior_temperature):
        return ""
    t = float(prior_temperature)
    return "-vprior" if t == 1.0 else f"-vprior{t:g}"


def leaf_suffix(leaf: str = "net", leaf_playouts: int = 1) -> str:
    """``""`` for the net leaf; ``-pleaf`` / ``-pleaf<n>`` for a playout leaf."""
    if not leaf_identity(leaf, leaf_playouts):
        return ""
    return "-pleaf" if int(leaf_playouts) == 1 else f"-pleaf{int(leaf_playouts)}"


def puct_policy_name(ckpt8: str, simulations: int, *, leaf: str = "net",
                     leaf_playouts: int = 1, prior: str = "uniform",
                     prior_temperature: float = DEFAULT_PRIOR_TEMPERATURE) -> str:
    return (f"mc-cwvpuct-{ckpt8}-s{int(simulations)}"
            f"{prior_suffix(prior, prior_temperature)}{leaf_suffix(leaf, leaf_playouts)}")


def puct_control_name(ckpt8: str, simulations: int, *, leaf: str = "net",
                      leaf_playouts: int = 1, prior: str = "uniform",
                      prior_temperature: float = DEFAULT_PRIOR_TEMPERATURE) -> str:
    """The control is always the uniform prior: no prior suffix."""
    del prior, prior_temperature
    return f"mc-cwvpuct-prior-{ckpt8}-s{int(simulations)}{leaf_suffix(leaf, leaf_playouts)}"


@lru_cache(maxsize=None)
def _bot_class(simulations: int, world_pool: int, batch: int, c_puct: float,
               prior: str, virtual_loss: float, alpha: float, epsilon: float,
               leaf: str = "net", leaf_playouts: int = 1,
               prior_temperature: float = DEFAULT_PRIOR_TEMPERATURE) -> type:
    name = (f"CWVPuct_s{simulations}_w{world_pool}_k{batch}_c{c_puct:g}_{prior}"
            + prior_suffix(prior, prior_temperature).replace("-", "_").replace(".", "p")
            + leaf_suffix(leaf, leaf_playouts).replace("-", "_"))
    return type(name, (CWVPuctBot,), {
        "CWV_SIMULATIONS": int(simulations), "CWV_WORLD_POOL": int(world_pool),
        "CWV_BATCH": int(batch), "CWV_C_PUCT": float(c_puct), "CWV_PRIOR": prior,
        "CWV_VIRTUAL_LOSS": float(virtual_loss),
        "CWV_DIRICHLET_ALPHA": float(alpha), "CWV_DIRICHLET_EPSILON": float(epsilon),
        "CWV_LEAF": leaf, "CWV_LEAF_PLAYOUTS": int(leaf_playouts),
        "CWV_PRIOR_TEMPERATURE": float(prior_temperature)})


def make_cwv_puct_bot(checkpoint: str | os.PathLike[str], *, simulations: int,
                      seed: int | None = None, world_pool: int = DEFAULT_WORLD_POOL,
                      batch: int = DEFAULT_BATCH, c_puct: float = DEFAULT_C_PUCT,
                      prior: str = "uniform",
                      prior_checkpoint: str | os.PathLike[str] | None = None,
                      control: bool = False,
                      receipt: str | os.PathLike[str] | None = None,
                      virtual_loss: float = DEFAULT_VIRTUAL_LOSS,
                      dirichlet_alpha: float = 0.0, dirichlet_epsilon: float = 0.0,
                      threads: int | None = 1, leaf: str = "net",
                      leaf_playouts: int = 1,
                      prior_temperature: float = DEFAULT_PRIOR_TEMPERATURE) -> CWVPuctBot:
    if prior not in PRIOR_MODES:
        raise CWVError(f"prior mode must be one of {PRIOR_MODES}")
    leaf_identity(leaf, leaf_playouts)                 # validates
    prior_identity(prior, prior_temperature)
    if prior == "head" and not control and prior_checkpoint is None:
        raise CWVError("prior='head' needs --prior-checkpoint")
    if control:
        evaluator: Any = prior_evaluator_for(checkpoint, receipt=receipt)
        prior_mode = "uniform"            # the control isolates the tree
        head = None
    else:
        evaluator = shared_evaluator(checkpoint, threads=threads)
        prior_mode = prior
        head = None
        if prior == "head":
            if prior_checkpoint is None:
                raise CWVError("prior='head' needs --prior-checkpoint")
            head = shared_prior_head(prior_checkpoint)
    cls = _bot_class(int(simulations), int(world_pool), int(batch), float(c_puct),
                     prior_mode, float(virtual_loss), float(dirichlet_alpha),
                     float(dirichlet_epsilon), leaf, int(leaf_playouts),
                     float(prior_temperature))
    bot = cls(seed, evaluator=evaluator, prior_head=head)
    bot.cwv_checkpoint_sha256 = evaluator.checkpoint_sha256
    bot.cwv_ckpt8 = evaluator.ckpt8
    return bot


def cwv_puct_registry_entries(checkpoint: str | os.PathLike[str],
                              simulations: Sequence[int], *,
                              world_pool: int = DEFAULT_WORLD_POOL,
                              batch: int = DEFAULT_BATCH,
                              c_puct: float = DEFAULT_C_PUCT,
                              prior: str = "uniform",
                              prior_checkpoint: str | os.PathLike[str] | None = None,
                              receipt: str | os.PathLike[str] | None = None,
                              virtual_loss: float = DEFAULT_VIRTUAL_LOSS,
                              dirichlet_alpha: float = 0.0,
                              dirichlet_epsilon: float = 0.0,
                              leaf: str = "net", leaf_playouts: int = 1,
                              prior_temperature: float = DEFAULT_PRIOR_TEMPERATURE
                              ) -> dict[str, Any]:
    """``{name: factory}`` per S: ``mc-cwvpuct-<ckpt8>-s<S>[-vprior[<T>]][-pleaf[<n>]]``
    and its control.

    The name binds the VALUE checkpoint, the simulation budget, the value
    prior (``-vprior``/``-vprior<T>`` for ``prior="value"`` at temperature
    T; nothing for uniform / head) and the leaf mode (``-pleaf``/
    ``-pleaf<n>`` for ``leaf="playout"`` with ``n`` playouts per leaf;
    nothing for the net leaf); the remaining search parameters (W, K,
    c_puct, prior mode and prior checkpoint) are part of the bot's
    ``search_identity`` and of the duel's calibration binding.
    """
    ckpt8 = checkpoint_id(checkpoint)
    leaf_identity(leaf, leaf_playouts)                 # validates
    prior_identity(prior, prior_temperature)
    entries: dict[str, Any] = {}

    def factory(s: int, control: bool):
        def make(**kw):
            return make_cwv_puct_bot(
                checkpoint, simulations=s, seed=kw.get("seed"), world_pool=world_pool,
                batch=batch, c_puct=c_puct, prior=prior, prior_checkpoint=prior_checkpoint,
                control=control, receipt=receipt, virtual_loss=virtual_loss,
                dirichlet_alpha=dirichlet_alpha, dirichlet_epsilon=dirichlet_epsilon,
                leaf=leaf, leaf_playouts=leaf_playouts, prior_temperature=prior_temperature)
        return make

    names = dict(leaf=leaf, leaf_playouts=leaf_playouts, prior=prior,
                 prior_temperature=prior_temperature)
    for s in sorted({int(s) for s in simulations}):
        if s < 1:
            raise CWVError("simulations must be positive")
        entries[puct_policy_name(ckpt8, s, **names)] = factory(s, False)
        entries[puct_control_name(ckpt8, s, **names)] = factory(s, True)
    return entries
