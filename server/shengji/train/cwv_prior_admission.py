"""DEV-only learned-prior admission for the exhaustive CWV shortlist (#425 step 4).

At a decision whose legal population exceeds ``threshold`` actions, the
root-state policy prior (``policy_prior``, #419) is run ONCE PER SAMPLED
WORLD on a root clone carrying that world's hands and kitty, exactly the
shape of the prior's training roots.  Each world admits its top-``top``
candidates by the factorised card score; the admission pool is the UNION of
those sets with every production-ballot anchor.  Only the pool is then ranked
by the value net over all sampled worlds (the ordinary one-stage path); every
other action scores ``-inf``.  Below the threshold nothing changes.

The prior never sees the engine's true hidden hands: it reads the same
determinized worlds the value ranking reads.  The pool size is the actual
union cardinality (up to worlds x top) and is logged per decision, together
with the prior's own wall; the whole stage runs inside the play deadline.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import copy
import hashlib
import math
import time

import numpy as np

from ..engine.round import Trick, TrickPlay
from .cwv_shortlist import CWVShortlistBot, CWVShortlistConfig

SCHEMA = "cwv-prior-admission-v1"


@dataclass(frozen=True)
class CWVPriorAdmissionConfig:
    """The prior-admission fields; the shortlist config stays separate."""

    checkpoint: str
    checkpoint_sha256: str
    threshold: int = 10_000
    top: int = 256
    schema: str = SCHEMA

    def __post_init__(self):
        if type(self.checkpoint) is not str or not self.checkpoint:
            raise ValueError("prior checkpoint path required")
        if type(self.checkpoint_sha256) is not str or len(self.checkpoint_sha256) != 64:
            raise ValueError("prior checkpoint_sha256 must be a full SHA256")
        for name in ("threshold", "top"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.schema != SCHEMA:
            raise ValueError("prior admission schema drift")


_PRIORS: dict[tuple[str, str], tuple] = {}


def load_prior_checked(path: str, sha256: str):
    """The prior, verified against the bound SHA256 (cached per process): either a
    standalone ``policy_prior`` checkpoint (``("separate", net, payload)``) or a
    value checkpoint carrying a policy head (#425 joint net; ``("joint", model,
    None)``), whose head reads the trunk features of the flat root row."""
    key = (path, sha256)
    if key not in _PRIORS:
        with open(path, "rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != sha256:
            raise ValueError("prior checkpoint SHA256 mismatch")
        if str(path).lower().endswith(".npz"):
            # The served form (#435): a NumPy prior package; no Torch on this path.
            from ..ai.cwv_prior_numpy import load_numpy_prior
            _PRIORS[key] = ("separate-numpy", load_numpy_prior(path), None)
            return _PRIORS[key]
        from .policy_prior import PolicyPriorError, load_prior
        try:
            net, payload = load_prior(path)
            _PRIORS[key] = ("separate", net, payload)
        except PolicyPriorError:
            from .train_cwv import load_cwv_checkpoint
            model, _meta, _aux = load_cwv_checkpoint(path, "cpu")
            if not getattr(model.config, "policy_head", False):
                raise ValueError("prior checkpoint is neither a policy prior nor a value net with a policy head")
            model.eval()
            _PRIORS[key] = ("joint", model, None)
    return _PRIORS[key]


def root_clone(rnd, hands, buried):
    """The decision root with one sampled world substituted for the hidden
    hands: ``cwv_policy.afterstate``'s clone before any card is played."""
    clone = copy.copy(rnd)
    clone.hands = [list(hand) for hand in hands]
    clone.buried = list(buried)
    if rnd.trick is not None:
        clone.trick = Trick(leader=rnd.trick.leader,
                            plays=[TrickPlay(p.seat, list(p.cards)) for p in rnd.trick.plays])
    clone.history = list(rnd.history)
    clone.last_trick = rnd.last_trick
    clone.message = None
    clone._trusted_rollout = True
    clone._determinized_world = True
    return clone


class CWVPriorAdmissionBot(CWVShortlistBot):
    """Learned W32 shortlist whose wide decisions are pruned by the policy prior."""

    def __init__(self, evaluator, *, seed=0, config=None, prior=None,
                 reuse_successors=False, capture_full_legal_scores=False):
        if prior is None and isinstance(config, CWVPriorAdmissionConfig):
            prior, config = config, None
        if not isinstance(prior, CWVPriorAdmissionConfig):
            raise TypeError("prior admission recipe must be CWVPriorAdmissionConfig")
        if config is None:
            config = CWVShortlistConfig(worlds=32, selection_worlds=30, alternatives=4)
        if not isinstance(config, CWVShortlistConfig):
            raise TypeError("shortlist config must be CWVShortlistConfig")
        if config.uniform:
            raise ValueError("prior admission requires the learned shortlist")
        if prior.top < config.alternatives + 1:
            raise ValueError("prior top must retain incumbent plus alternatives")
        if capture_full_legal_scores:
            raise ValueError("prior admission does not support full legal score capture")
        self.prior_config = prior
        self._prior_kind, self._prior_net, self._prior_payload = load_prior_checked(
            prior.checkpoint, prior.checkpoint_sha256)
        self._prior_diagnostics = None
        super().__init__(evaluator, seed=seed, config=config,
                         reuse_successors=reuse_successors, capture_full_legal_scores=False)
        self.shortlist_counts.update(dict.fromkeys((
            "prior_decisions", "prior_forwards", "prior_union_actions", "prior_pool_actions"), 0))

    # -- the prior stage (instrumented as the "prior" deadline phase) ----------

    def _prior_scores(self, rnd, seat, actions, worlds):
        """``(worlds, actions)`` factorised prior scores: one root forward per world."""
        from .policy_prior import CARD_INDEX, N_CARDS, flat_input, root_tensors   # torch-free module level
        X = np.stack([flat_input(root_tensors(root_clone(rnd, hands, buried), seat))
                      for hands, buried in worlds]).astype(np.float32)
        log_odds = self._prior_log_odds(X)
        if log_odds.shape != (len(worlds), N_CARDS) or not np.isfinite(log_odds).all():
            raise ValueError("prior log-odds must be finite, one row per world")
        # Multiplicity matrix: score(action) = sum over its cards of the card log-odds.
        multiplicity = np.zeros((len(actions), N_CARDS), dtype=np.float32)
        for index, action in enumerate(actions):
            for card in action:
                multiplicity[index, CARD_INDEX[card]] += 1.0
        return (log_odds.astype(np.float32) @ multiplicity.T).astype(np.float64)

    def _prior_log_odds(self, X):
        if self._prior_kind == "separate-numpy":
            return self._prior_net.log_odds(X)
        if self._prior_kind == "joint":
            from .policy_rows import policy_log_odds
            return np.asarray(policy_log_odds(self._prior_net, X, "cpu"), dtype=np.float64)
        from .policy_prior import predict_log_odds
        return np.asarray(predict_log_odds(self._prior_net, self._prior_payload, X), dtype=np.float64)

    # -- admission ------------------------------------------------------------

    def _admission_means(self, rnd, seat, actions, worlds, production):
        self._prior_diagnostics = None
        cfg = self.prior_config
        if len(actions) <= cfg.threshold:
            return self._means(rnd, seat, actions, worlds)
        if len(actions) < self.shortlist_config.alternatives + 1:
            raise ValueError("prior admission legal population is smaller than shortlist")
        keys = [tuple(sorted(action)) for action in actions]
        production_indices = []
        for key in {tuple(sorted(action)) for action in production}:
            try:
                production_indices.append(keys.index(key))
            except ValueError as exc:
                raise ValueError("prior admission production anchor missing from legal population") from exc

        started = time.perf_counter()
        scores = self._prior_scores(rnd, seat, actions, worlds)
        if scores.shape != (len(worlds), len(actions)):
            raise ValueError("prior scores must cover every world and action")
        top = min(cfg.top, len(actions))
        union: set[int] = set()
        per_world = []
        for row in scores:
            # Deterministic: score descending, then enumeration order.
            order = np.lexsort((np.arange(len(actions)), -row))[:top]
            chosen = [int(i) for i in order]
            per_world.append(chosen)
            union.update(chosen)
        prior_seconds = time.perf_counter() - started
        anchors = set(production_indices)
        pool_indices = sorted(union | anchors)
        if len(pool_indices) < self.shortlist_config.alternatives + 1:
            raise ValueError("prior admission pool must retain incumbent plus alternatives")

        pool_actions = [actions[index] for index in pool_indices]
        refined = np.asarray(self._means(rnd, seat, pool_actions, worlds), dtype=np.float64)
        if refined.shape != (len(pool_indices),) or not np.isfinite(refined).all():
            raise ValueError("prior admission pool means must be finite")
        means = np.full(len(actions), -math.inf, dtype=np.float64)
        means[pool_indices] = refined

        self.shortlist_counts["prior_decisions"] += 1
        self.shortlist_counts["prior_forwards"] += len(worlds)
        self.shortlist_counts["prior_union_actions"] += len(union)
        self.shortlist_counts["prior_pool_actions"] += len(pool_indices)
        self._prior_diagnostics = {
            "triggered": True, "recipe": asdict(cfg),
            "legal_count": len(actions), "worlds": len(worlds), "top": top,
            "union_size": len(union),                         # actual cardinality, not top
            "anchors_added": len(anchors - union),
            "pool_action_count": len(pool_indices),
            "pool_evaluations": len(pool_indices) * len(worlds),
            "cap_rule": "none (union of per-world top lists, bounded by worlds x top)",
            "prior_seconds": prior_seconds,
            "ranking_basis": "prior-union-then-world-mean",
            "prior_checkpoint_sha256": cfg.checkpoint_sha256,
            "prior_kind": self._prior_kind,
        }
        return means

    def _candidates(self, rnd, seat):
        self._prior_diagnostics = None
        selected = super()._candidates(rnd, seat)
        detail = self.last_shortlist
        diagnostic = self._prior_diagnostics
        if diagnostic is not None and detail is not None:
            shortlist_means = detail.get("shortlist_means") or []
            if not shortlist_means or not np.isfinite(np.asarray(shortlist_means, dtype=float)).all():
                raise ValueError("prior admission selected means must be finite")
            detail["prior_admission"] = diagnostic
            detail["ranking_basis"] = "prior-union-then-world-mean"
            detail["full_legal_world_means_complete"] = False
        return selected


__all__ = ["CWVPriorAdmissionBot", "CWVPriorAdmissionConfig", "SCHEMA", "load_prior_checked", "root_clone"]
