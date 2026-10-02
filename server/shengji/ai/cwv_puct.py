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
production's playouts.  ``prior="package"`` (#436 step 1) prices the ballot
by the joint NumPy serving package's POLICY head (``JointPackagePriorHead``):
the card log-odds sum per action over the ``policy_prior`` root rows of the
sampled worlds -- ``train.cwv_prior_admission.prior_scores``, the served
admission's own scoring path -- softmaxed at ``prior_temperature``; at the
root the scores are averaged over the world pool (production's
``.mean(axis=0)`` preference), below the root the acting seat's node is
priced in the current world.

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
prior table) is then only the prior.  ``leaf_finish_trick`` (net leaf only,
off by default) hands the evaluator not the reached leaf but its
AFTERSTATE BOUNDARY: the current trick finished by production's heuristic
(``cwv_policy.finish_current_trick``, the ``afterstate(...,
finish_trick=True)`` path pv-search serves), so the outcome head is read at
the boundary it was trained and served on.  The tree's leaf stays as
reached; only the scored position moves, and only within the trick.

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
    finish_current_trick,
    prior_evaluator_for,
    sample_worlds,
    shared_evaluator,
)
from .mcbot import MCBot, _ballot_identity, _runtime_identity
from .memory import Memory


CWV_PUCT_DECISION_SCHEMA = "cwv-puct-decision-v1"
PRIOR_MODES = ("uniform", "head", "value", "package")
HEAD_PRIORS = ("head", "package")      # priors served by a prior-head object
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

    @property
    def enc_version(self) -> int:
        """The encoder version the LOADED prior head was trained on."""
        from ..rl.encode_versions import ENC_VERSION
        version = getattr(self.model, "enc_version", None)
        return ENC_VERSION if version is None else int(version)

    def encode(self, rnd: Round, seat: int, ballot: Sequence[Sequence[str]]
               ) -> tuple[np.ndarray, np.ndarray]:
        """``(obs, cand)`` rows of one request, encoded NOW (the world clone
        keeps moving; nothing of it is retained)."""
        from ..rl.encode import ACT_DIM, encode_action
        from ..rl.encode_versions import call_encode, encode_obs

        if not ballot:
            raise CWVError("prior head received an empty ballot")
        obs = np.asarray(call_encode(encode_obs, rnd, seat, self.enc_version),
                         dtype=np.float32)
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


class JointPackagePriorHead:
    """The joint NumPy serving package's POLICY head as a PUCT prior (#436 step 1).

    One ``.npz`` package serves production's value head and, through
    ``train.cwv_prior_admission.load_prior_checked`` (kind ``joint-numpy``),
    its policy head.  This adapter reads the package the way the served prior
    admission does -- the SHA256 is pinned and a mismatch refuses -- and prices
    a ballot by ``prior_scores``: the sum over an action's cards of the head's
    card log-odds on ``policy_prior.flat_input(root_tensors(root_clone(...)))``
    rows.  Nothing here re-derives the encoding or the arithmetic; the served
    admission (`CWVPriorAdmissionBot._prior_scores`) calls the same function.

    Root: ``root_probabilities(rnd, seat, ballot, worlds)`` = softmax over the
    ballot of the scores AVERAGED over the sampled world pool, at
    ``temperature`` (a world-dependent prior, as ``prior="value"``: the true
    hidden hands are never encoded).  Below the root: ``encode`` builds the
    acting seat's row in the CURRENT world (the clone's own hands) and
    ``batch_from_encoded`` serves many nodes in one forward -- the hooks
    ``CWVPuctBot`` uses for ``prior="head"``.
    """

    def __init__(self, package: str | os.PathLike[str], sha256: str, *,
                 temperature: float = DEFAULT_PRIOR_TEMPERATURE):
        from ..train.cwv_prior_admission import load_prior_checked, prior_encoder_version
        t = float(temperature)
        if not (t > 0.0) or not math.isfinite(t):
            raise CWVError("prior temperature must be a positive finite number")
        if type(sha256) is not str or len(sha256) != 64:
            raise CWVError("the package prior needs its full pinned SHA256")
        self.package_path = str(Path(package).resolve())
        self.package_sha256 = sha256
        try:
            kind, net, payload = load_prior_checked(self.package_path, sha256)
        except (ValueError, OSError) as exc:
            raise CWVError(f"package prior refused: {exc}") from exc
        if kind != "joint-numpy":
            raise CWVError("the package prior reads a joint NumPy value+policy package; "
                           f"{self.package_path} loaded as {kind!r}")
        # the triple `CWVPriorAdmissionBot._prior_log_odds` dispatches on
        self._prior_kind, self._prior_net, self._prior_payload = kind, net, payload
        self.version = prior_encoder_version(kind, net, payload)
        self.temperature = t
        self.forward_calls = 0
        self.rows = 0
        self.wall_secs = 0.0

    @property
    def checkpoint_sha256(self) -> str:
        return self.package_sha256

    @property
    def ckpt8(self) -> str:
        return self.package_sha256[:8]

    def identity(self) -> dict[str, Any]:
        return {"kind": "joint_package_policy_head", "package": self.package_path,
                "checkpoint_sha256": self.package_sha256, "ckpt8": self.ckpt8,
                "prior_kind": self._prior_kind, "encoder_version": int(self.version),
                "temperature": float(self.temperature),
                "source_checkpoint_sha256": self._prior_net.original_checkpoint_sha256}

    # -- the shared scoring path ---------------------------------------
    def log_odds(self, X: np.ndarray) -> np.ndarray:
        """``(rows, 54)`` card log-odds: serving's dispatch, verbatim."""
        from ..train.cwv_prior_admission import CWVPriorAdmissionBot
        wall0 = time.perf_counter()
        out = CWVPriorAdmissionBot._prior_log_odds(self, X)
        self.forward_calls += 1
        self.rows += len(X)
        self.wall_secs += time.perf_counter() - wall0
        return out

    def scores(self, rnd: Round, seat: int, ballot: Sequence[Sequence[str]],
               worlds: Sequence) -> np.ndarray:
        """``(worlds, ballot)``: exactly `CWVPriorAdmissionBot._prior_scores`."""
        from ..train.cwv_prior_admission import prior_scores
        if not ballot:
            raise CWVError("prior head received an empty ballot")
        if not worlds:
            raise CWVError("the package prior needs at least one sampled world")
        return prior_scores(self.log_odds, self.version, rnd, seat,
                            [list(a) for a in ballot], worlds)

    def root_probabilities(self, rnd: Round, seat: int, ballot: Sequence[Sequence[str]],
                           worlds: Sequence) -> np.ndarray:
        """Softmax at ``temperature`` of the pool-mean scores over the ballot."""
        return value_prior(self.scores(rnd, seat, ballot, worlds).mean(axis=0),
                           self.temperature)

    def probabilities(self, rnd: Round, seat: int, ballot: Sequence[Sequence[str]]
                      ) -> np.ndarray:
        raise CWVError("the package prior encodes sampled worlds, never the true "
                       "hidden hands: use root_probabilities(rnd, seat, ballot, worlds)")

    # -- the tree's batched hooks (one world: the clone's own hands) -------
    def encode(self, clone: Round, seat: int, ballot: Sequence[Sequence[str]]
               ) -> tuple[np.ndarray, list[list[str]]]:
        """``(row, ballot)`` of one request, encoded NOW in the world the clone
        carries (the clone keeps moving; nothing of it is retained)."""
        from ..train.cwv_prior_admission import prior_rows
        if not ballot:
            raise CWVError("prior head received an empty ballot")
        row = prior_rows(clone, seat, [(clone.hands, clone.buried)], self.version)[0]
        return row, [list(a) for a in ballot]

    def batch_from_encoded(self, rows: Sequence[tuple[np.ndarray, Sequence[Sequence[str]]]]
                           ) -> list[np.ndarray]:
        """One forward for many encoded requests; per request the softmax of
        its ballot's card-sum scores at ``temperature``."""
        from ..train.cwv_prior_admission import action_scores
        if not rows:
            return []
        X = np.stack([row for row, _ballot in rows]).astype(np.float32)
        log_odds = np.asarray(self.log_odds(X))
        if log_odds.ndim != 2 or log_odds.shape[0] != len(rows):
            raise CWVError("package prior returned a misaligned log-odds batch")
        result = []
        for index, (_row, ballot) in enumerate(rows):
            scores = action_scores(log_odds[index:index + 1], ballot)[0]
            result.append(value_prior(scores, self.temperature))
        return result


@lru_cache(maxsize=4)
def _shared_package_prior_head(path: str, sha256: str, temperature: float
                               ) -> JointPackagePriorHead:
    return JointPackagePriorHead(path, sha256, temperature=temperature)


def shared_package_prior_head(package: str | os.PathLike[str], sha256: str, *,
                              temperature: float = DEFAULT_PRIOR_TEMPERATURE
                              ) -> JointPackagePriorHead:
    """One adapter per (package, pinned sha, temperature) per process; the
    package itself is cached once by ``load_prior_checked``."""
    resolved = Path(package).resolve()
    if not resolved.is_file():
        raise CWVError(f"prior package not found: {resolved}")
    return _shared_package_prior_head(str(resolved), str(sha256), float(temperature))


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


def leaf_boundary(leaf: Round) -> Round:
    """The afterstate boundary of a reached leaf: a private copy in which
    production's heuristic finishes the CURRENT trick and nothing more
    (``cwv_policy.finish_current_trick`` with the default finisher, the
    ``afterstate(..., finish_trick=True)`` path pv-search serves).  A leaf at
    a trick start, or terminal, comes back as an untouched copy."""
    boundary = leaf_copy(leaf)
    finish_current_trick(boundary)
    return boundary


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
    ``head`` add nothing (the v1 record / binding, unchanged); ``value`` and
    ``package`` bind their softmax temperature."""
    if prior not in PRIOR_MODES:
        raise CWVError(f"prior mode must be one of {PRIOR_MODES}")
    t = float(prior_temperature)
    if not (t > 0.0) or not math.isfinite(t):
        raise CWVError("prior temperature must be a positive finite number")
    if prior not in ("value", "package"):
        return {}
    return {"prior_temperature": t}


def leaf_identity(leaf: str, leaf_playouts: int,
                  leaf_finish_trick: bool = False) -> dict[str, Any]:
    """The leaf's identity keys.  ``net`` is the implicit default of the
    v1 record / calibration binding (no keys: nothing existing changes);
    ``playout`` binds the mode and the playouts per leaf, so a binding or a
    record made under one leaf never matches the other.  ``leaf_finish_trick``
    (net leaf only: a playout already plays through the trick) adds its own
    key only when on."""
    if leaf not in LEAF_MODES:
        raise CWVError(f"leaf mode must be one of {LEAF_MODES}")
    if int(leaf_playouts) < 1:
        raise CWVError("leaf_playouts must be positive")
    if leaf_finish_trick and leaf != "net":
        raise CWVError("leaf_finish_trick applies to the net leaf only")
    if leaf == "net":
        return {"leaf_finish_trick": True} if leaf_finish_trick else {}
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
    CWV_LEAF_FINISH_TRICK = False  # net leaf scored at the finished-trick boundary
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
        if self.CWV_PRIOR in HEAD_PRIORS and (
                prior_head is None or not hasattr(prior_head, "batch_from_encoded")
                or not hasattr(prior_head, "encode")):
            raise CWVError(f"prior={self.CWV_PRIOR!r} needs a prior head with encode() and "
                           "batch_from_encoded()")
        if self.CWV_PRIOR == "package" and not hasattr(prior_head, "root_probabilities"):
            raise CWVError("prior='package' needs a prior head with root_probabilities()")
        if self.CWV_PRIOR == "value" and not hasattr(evaluator, "score_many"):
            raise CWVError("prior='value' needs an evaluator with score_many()")
        prior_identity(self.CWV_PRIOR, self.CWV_PRIOR_TEMPERATURE)   # validates
        leaf_identity(self.CWV_LEAF, self.CWV_LEAF_PLAYOUTS, self.CWV_LEAF_FINISH_TRICK)
        if int(self.CWV_SIMULATIONS) < 1 or int(self.CWV_WORLD_POOL) < 1 \
                or int(self.CWV_BATCH) < 1:
            raise CWVError("simulations, world pool and batch must be positive")
        self.evaluator = evaluator
        self.prior_head = prior_head if self.CWV_PRIOR in HEAD_PRIORS else None
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
                **leaf_identity(self.CWV_LEAF, self.CWV_LEAF_PLAYOUTS,
                                self.CWV_LEAF_FINISH_TRICK)}

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
        elif self.CWV_PRIOR == "package":
            wall0 = time.perf_counter()
            # the pool-mean of the package policy's card-sum scores over the
            # sampled worlds (never the true hidden hands), softmaxed
            probs = self.prior_head.root_probabilities(
                rnd, seat, [list(c) for c in candidates], worlds)
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
        finish_leaf = bool(self.CWV_LEAF_FINISH_TRICK) and not playout_leaf
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
                # the scored positions: the leaves as reached, or (finish-trick
                # boundary) private copies with the current trick finished
                scored = [leaf_boundary(leaf) for leaf in leaves] if finish_leaf else leaves
                values = np.asarray(self.evaluator.score(scored, seat), dtype=np.float64)
            stats["batch_wall"] += time.perf_counter() - wall0
            stats["batch_cpu"] += time.process_time() - cpu0
            if values.shape != (batch,):
                raise CWVError("evaluator returned a misaligned value vector")
            self._serve_prior_requests(prior_requests)
            for index, (path, leaf, value, tr, edges) in enumerate(
                    zip(paths, leaves, values, traces, edge_paths)):
                backup(path, float(value), edges)
                depth = len(path) - 1
                stats["max_depth"] = max(stats["max_depth"], depth)
                stats["depth_sum"] += depth
                if leaf.phase == "round_end":
                    stats["terminal_leaves"] += 1
                if tr is not None:
                    tr["value"] = float(value)
                    tr["leaf"] = leaf
                    if finish_leaf:
                        tr["boundary"] = scored[index]
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
            # PUCT runs NO disjoint report fold: it requests exactly 0 report
            # worlds and names no report challenger, which is what an MCBot with
            # REPORT_FOLD_WORLDS=0 publishes. A literal 0, not the inherited
            # REPORT_FOLD_WORLDS, because this decide_play never reads that knob.
            # The screen's TimedPolicy indexes these for every record carrying
            # candidates; their absence aborted lane PUCT P1 (#436, 2026-10-02).
            "report_worlds_requested": 0,
            "report_candidate_index": None,
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
    """``""`` for uniform / head; ``-vprior`` / ``-vprior<T>`` for the value
    prior; ``-pprior`` / ``-pprior-T<T>`` for the package policy prior."""
    if not prior_identity(prior, prior_temperature):
        return ""
    t = float(prior_temperature)
    if prior == "package":
        return "-pprior" if t == 1.0 else f"-pprior-T{t:g}"
    return "-vprior" if t == 1.0 else f"-vprior{t:g}"


def leaf_suffix(leaf: str = "net", leaf_playouts: int = 1,
                leaf_finish_trick: bool = False) -> str:
    """``""`` for the net leaf (``-ftl`` when scored at the finished-trick
    boundary); ``-pleaf`` / ``-pleaf<n>`` for a playout leaf."""
    keys = leaf_identity(leaf, leaf_playouts, leaf_finish_trick)
    if not keys:
        return ""
    if leaf == "net":
        return "-ftl"
    return "-pleaf" if int(leaf_playouts) == 1 else f"-pleaf{int(leaf_playouts)}"


def puct_policy_name(ckpt8: str, simulations: int, *, leaf: str = "net",
                     leaf_playouts: int = 1, prior: str = "uniform",
                     prior_temperature: float = DEFAULT_PRIOR_TEMPERATURE,
                     leaf_finish_trick: bool = False, prior8: str | None = None) -> str:
    """``mc-cwvpuct-<ckpt8>[-prior-<prior8>]-s<S>[-pprior[-T<T>]|-vprior[<T>]][-ftl|-pleaf[<n>]]``.
    ``prior8`` names a package prior that is NOT the value package (the #436
    arm binds one package to both roles and carries no ``-prior-``)."""
    prior_part = f"-prior-{prior8}" if prior8 else ""
    return (f"mc-cwvpuct-{ckpt8}{prior_part}-s{int(simulations)}"
            f"{prior_suffix(prior, prior_temperature)}"
            f"{leaf_suffix(leaf, leaf_playouts, leaf_finish_trick)}")


def puct_control_name(ckpt8: str, simulations: int, *, leaf: str = "net",
                      leaf_playouts: int = 1, prior: str = "uniform",
                      prior_temperature: float = DEFAULT_PRIOR_TEMPERATURE,
                      leaf_finish_trick: bool = False, prior8: str | None = None) -> str:
    """The control is always the uniform prior: no prior suffix, no prior id."""
    del prior, prior_temperature, prior8
    return (f"mc-cwvpuct-prior-{ckpt8}-s{int(simulations)}"
            f"{leaf_suffix(leaf, leaf_playouts, leaf_finish_trick)}")


@lru_cache(maxsize=None)
def _bot_class(simulations: int, world_pool: int, batch: int, c_puct: float,
               prior: str, virtual_loss: float, alpha: float, epsilon: float,
               leaf: str = "net", leaf_playouts: int = 1,
               prior_temperature: float = DEFAULT_PRIOR_TEMPERATURE,
               leaf_finish_trick: bool = False) -> type:
    name = (f"CWVPuct_s{simulations}_w{world_pool}_k{batch}_c{c_puct:g}_{prior}"
            + prior_suffix(prior, prior_temperature).replace("-", "_").replace(".", "p")
            + leaf_suffix(leaf, leaf_playouts, leaf_finish_trick).replace("-", "_"))
    return type(name, (CWVPuctBot,), {
        "CWV_SIMULATIONS": int(simulations), "CWV_WORLD_POOL": int(world_pool),
        "CWV_BATCH": int(batch), "CWV_C_PUCT": float(c_puct), "CWV_PRIOR": prior,
        "CWV_VIRTUAL_LOSS": float(virtual_loss),
        "CWV_DIRICHLET_ALPHA": float(alpha), "CWV_DIRICHLET_EPSILON": float(epsilon),
        "CWV_LEAF": leaf, "CWV_LEAF_PLAYOUTS": int(leaf_playouts),
        "CWV_PRIOR_TEMPERATURE": float(prior_temperature),
        "CWV_LEAF_FINISH_TRICK": bool(leaf_finish_trick)})


def check_pin(path: str | os.PathLike[str], sha256: str, label: str) -> None:
    """Refuse unless ``path`` hashes to the pinned ``sha256`` NOW."""
    if type(sha256) is not str or len(sha256) != 64:
        raise CWVError(f"{label} pin must be a full sha256")
    resolved = Path(path)
    if not resolved.is_file():
        raise CWVError(f"{label} not found: {resolved}")
    actual = file_sha256(resolved)
    if actual != sha256:
        raise CWVError(f"{label} {resolved} hashes to {actual[:8]}, pinned {sha256[:8]}: "
                       "refusing to build the bot")


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
                      prior_temperature: float = DEFAULT_PRIOR_TEMPERATURE,
                      prior_sha256: str | None = None,
                      leaf_finish_trick: bool = False,
                      checkpoint_sha256: str | None = None) -> CWVPuctBot:
    """``prior="package"``: ``prior_checkpoint`` is the joint NumPy package and
    ``prior_sha256`` its pinned SHA256 (both required; a mismatch refuses).

    ``checkpoint_sha256`` pins the VALUE checkpoint: when given, the file is
    hashed HERE, at every construction (a registry factory runs in a worker
    long after registration), and a mismatch refuses -- for every prior mode
    and for the control.  A given ``prior_sha256`` is enforced the same way
    on the prior file before any cache is consulted."""
    if prior not in PRIOR_MODES:
        raise CWVError(f"prior mode must be one of {PRIOR_MODES}")
    if checkpoint_sha256 is not None:
        check_pin(checkpoint, checkpoint_sha256, "value checkpoint")
    if prior_sha256 is not None and prior_checkpoint is not None and not control:
        check_pin(prior_checkpoint, prior_sha256, "prior checkpoint")
    leaf_identity(leaf, leaf_playouts, leaf_finish_trick)   # validates
    prior_identity(prior, prior_temperature)
    if prior == "head" and not control and prior_checkpoint is None:
        raise CWVError("prior='head' needs --prior-checkpoint")
    if prior == "package" and not control and (prior_checkpoint is None or prior_sha256 is None):
        raise CWVError("prior='package' needs the package path and its pinned sha256")
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
        elif prior == "package":
            head = shared_package_prior_head(prior_checkpoint, prior_sha256,
                                             temperature=prior_temperature)
    cls = _bot_class(int(simulations), int(world_pool), int(batch), float(c_puct),
                     prior_mode, float(virtual_loss), float(dirichlet_alpha),
                     float(dirichlet_epsilon), leaf, int(leaf_playouts),
                     float(prior_temperature), bool(leaf_finish_trick))
    bot = cls(seed, evaluator=evaluator, prior_head=head)
    bot.cwv_checkpoint_sha256 = evaluator.checkpoint_sha256
    bot.cwv_ckpt8 = evaluator.ckpt8
    return bot


PUCT_ENV_PREFIX = "SHENGJI_CWV_PUCT_"


def puct_env_recipe(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """``SHENGJI_CWV_PUCT_CKPT`` + ``_SHA256`` (both required: an unpinned package
    is refused, and the file must hash to the pin) and ``_SIMULATIONS`` (S, int);
    optional ``_PRIOR`` (``package`` by default, or ``uniform`` / ``head`` /
    ``value``), the ``_PRIOR_CKPT`` + ``_PRIOR_SHA256`` pair when the prior
    package is not the value package (under ``package`` the value package is
    the prior otherwise), ``_PRIOR_TEMPERATURE`` (float > 0),
    ``_LEAF_FINISH_TRICK`` (0/1), ``_WORLD_POOL`` / ``_BATCH`` (int) and
    ``_C_PUCT`` (float) -- as keyword arguments for `cwv_puct_registry_entries`
    plus ``checkpoint`` and ``simulations``.  Screen-only: the registry's
    import hook reads this so a spawned worker resolves the same name the
    parent did (#436 step 1b)."""
    env = os.environ if environ is None else environ
    checkpoint = env.get(PUCT_ENV_PREFIX + "CKPT")
    if not checkpoint:
        raise CWVError("SHENGJI_CWV_PUCT_CKPT is not set")
    sha256 = env.get(PUCT_ENV_PREFIX + "SHA256")
    if not sha256 or len(sha256) != 64:
        raise CWVError("SHENGJI_CWV_PUCT_SHA256 must be the package's full sha256")
    if not Path(checkpoint).is_file():
        raise CWVError(f"SHENGJI_CWV_PUCT_CKPT not found: {checkpoint}")
    if file_sha256(checkpoint) != sha256:
        raise CWVError("SHENGJI_CWV_PUCT_CKPT does not hash to SHENGJI_CWV_PUCT_SHA256")
    raw = env.get(PUCT_ENV_PREFIX + "SIMULATIONS")
    if raw in (None, ""):
        raise CWVError("SHENGJI_CWV_PUCT_SIMULATIONS is not set")
    simulations = [int(part) for part in str(raw).split(",") if part.strip()]
    if not simulations or any(s < 1 for s in simulations):
        raise CWVError("SHENGJI_CWV_PUCT_SIMULATIONS must be positive integers")
    prior = env.get(PUCT_ENV_PREFIX + "PRIOR") or "package"
    if prior not in PRIOR_MODES:
        raise CWVError(f"SHENGJI_CWV_PUCT_PRIOR must be one of {PRIOR_MODES}")
    recipe: dict[str, Any] = dict(checkpoint=checkpoint, checkpoint_sha256=sha256,
                                  simulations=simulations, prior=prior)
    prior_ckpt = env.get(PUCT_ENV_PREFIX + "PRIOR_CKPT")
    prior_sha = env.get(PUCT_ENV_PREFIX + "PRIOR_SHA256")
    if bool(prior_ckpt) != bool(prior_sha):
        raise CWVError("SHENGJI_CWV_PUCT_PRIOR_CKPT and SHENGJI_CWV_PUCT_PRIOR_SHA256 go together")
    if prior_ckpt:
        if len(prior_sha) != 64:
            raise CWVError("SHENGJI_CWV_PUCT_PRIOR_SHA256 must be the prior's full sha256")
        if not Path(prior_ckpt).is_file() or file_sha256(prior_ckpt) != prior_sha:
            raise CWVError("SHENGJI_CWV_PUCT_PRIOR_CKPT does not hash to SHENGJI_CWV_PUCT_PRIOR_SHA256")
        recipe.update(prior_checkpoint=prior_ckpt, prior_sha256=prior_sha)
    elif prior == "package":
        recipe.update(prior_checkpoint=checkpoint, prior_sha256=sha256)   # one package, both roles
    elif prior == "head":
        raise CWVError("SHENGJI_CWV_PUCT_PRIOR=head needs SHENGJI_CWV_PUCT_PRIOR_CKPT + _SHA256")
    raw = env.get(PUCT_ENV_PREFIX + "PRIOR_TEMPERATURE")
    if raw not in (None, ""):
        t = float(raw)
        if not (t > 0.0) or not math.isfinite(t):
            raise CWVError("SHENGJI_CWV_PUCT_PRIOR_TEMPERATURE must be a positive finite number")
        recipe["prior_temperature"] = t
    raw = env.get(PUCT_ENV_PREFIX + "LEAF_FINISH_TRICK")
    if raw not in (None, ""):
        if raw not in ("0", "1"):
            raise CWVError("SHENGJI_CWV_PUCT_LEAF_FINISH_TRICK must be 0 or 1")
        recipe["leaf_finish_trick"] = raw == "1"
    for key in ("world_pool", "batch"):
        raw = env.get(PUCT_ENV_PREFIX + key.upper())
        if raw not in (None, ""):
            recipe[key] = int(raw)
    raw = env.get(PUCT_ENV_PREFIX + "C_PUCT")
    if raw not in (None, ""):
        recipe["c_puct"] = float(raw)
    return recipe


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
                              prior_temperature: float = DEFAULT_PRIOR_TEMPERATURE,
                              prior_sha256: str | None = None,
                              leaf_finish_trick: bool = False,
                              checkpoint_sha256: str | None = None
                              ) -> dict[str, Any]:
    """``{name: factory}`` per S:
    ``mc-cwvpuct-<ckpt8>[-prior-<prior8>]-s<S>[-pprior[-T<T>]|-vprior[<T>]][-ftl|-pleaf[<n>]]``
    and its control.

    The name binds the VALUE checkpoint, the simulation budget, the prior
    (``-vprior``/``-vprior<T>`` for ``prior="value"``; ``-pprior``/
    ``-pprior-T<T>`` for the joint package's policy head, ``prior="package"``,
    plus ``-prior-<prior8>`` when that package is not the value package;
    nothing for uniform / head) and the leaf (``-pleaf``/``-pleaf<n>`` for
    ``leaf="playout"`` with ``n`` playouts per leaf; ``-ftl`` for the net
    leaf scored at the finished-trick boundary; nothing for the plain net
    leaf); the remaining search parameters (W, K, c_puct, prior mode and
    prior checkpoint) are part of the bot's ``search_identity`` and of the
    duel's calibration binding.  ``checkpoint_sha256`` (the value pin) and
    ``prior_sha256`` are carried INTO every factory, arm and control alike,
    and re-verified against the files at each construction.
    """
    value_sha = file_sha256(checkpoint)
    if checkpoint_sha256 is not None and value_sha != checkpoint_sha256:
        raise CWVError(f"value checkpoint {checkpoint} hashes to {value_sha[:8]}, pinned "
                       f"{str(checkpoint_sha256)[:8]}")
    ckpt8 = value_sha[:8]
    leaf_identity(leaf, leaf_playouts, leaf_finish_trick)   # validates
    prior_identity(prior, prior_temperature)
    prior8 = None
    if prior == "package":
        if prior_checkpoint is None or prior_sha256 is None:
            raise CWVError("prior='package' needs the package path and its pinned sha256")
        if value_sha != prior_sha256:
            prior8 = str(prior_sha256)[:8]
    entries: dict[str, Any] = {}

    def factory(s: int, control: bool):
        def make(**kw):
            return make_cwv_puct_bot(
                checkpoint, simulations=s, seed=kw.get("seed"), world_pool=world_pool,
                batch=batch, c_puct=c_puct, prior=prior, prior_checkpoint=prior_checkpoint,
                control=control, receipt=receipt, virtual_loss=virtual_loss,
                dirichlet_alpha=dirichlet_alpha, dirichlet_epsilon=dirichlet_epsilon,
                leaf=leaf, leaf_playouts=leaf_playouts, prior_temperature=prior_temperature,
                prior_sha256=prior_sha256, leaf_finish_trick=leaf_finish_trick,
                checkpoint_sha256=checkpoint_sha256)
        return make

    names = dict(leaf=leaf, leaf_playouts=leaf_playouts, prior=prior,
                 prior_temperature=prior_temperature, leaf_finish_trick=leaf_finish_trick,
                 prior8=prior8)
    for s in sorted({int(s) for s in simulations}):
        if s < 1:
            raise CWVError("simulations must be positive")
        entries[puct_policy_name(ckpt8, s, **names)] = factory(s, False)
        entries[puct_control_name(ckpt8, s, **names)] = factory(s, True)
    return entries
