"""DEV-only exhaustive legal shortlist, followed by unmodified MC-LCB search.

The model ranks submitted actions, including throws whose accepted component
depends on a sampled world. It never replaces a selection or report rollout.
No live registry entry is installed. Four alternatives plus the incumbent
means min(5, legal_count) actions in BOTH learned and uniform arms.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import random
import time

import numpy as np

from ..ai.cwv_policy import afterstate, sample_worlds
from ..ai.cwv_successor_reuse import TensorInputCache, WorldSuccessorCache
from ..ai.mcbot import _child_seed
from ..ai.registry import REGISTRY
from ..harvest.legal import enumerate_legal


@dataclass(frozen=True)
class CWVShortlistConfig:
    worlds: int = 1
    selection_worlds: int = 30
    alternatives: int = 4
    batch_size: int = 128
    uniform: bool = False

    def __post_init__(self):
        for name in ("worlds", "selection_worlds", "alternatives", "batch_size"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.uniform) is not bool:
            raise ValueError("uniform must be boolean")


class CWVShortlistBot(REGISTRY["mc-s0-report-lcb"]):
    # The full-legal request includes leads production would tractor-lock.
    # Only this candidate bypass changes; allocation, rollouts, report and
    # final point-shy tie-breaking are inherited from literal production.
    TRACTOR_LOCK = False
    #: The searched ballot is a shortlist over the EXHAUSTIVE legal set, so it
    #: differs from production's list on (nearly) every decision.  A harvest
    #: (``harvest/trajectory.py``) therefore attaches an unmodified instance of
    #: this policy as its ``production_probe`` and stamps ``production_ballot``
    #: on every record: the ballot-gap and prior analyses read that field as
    #: "what production would have considered".
    PRODUCTION_BALLOT_POLICY = "mc-s0-report-lcb"

    def __init__(self, evaluator, *, seed=0, config=None, reuse_successors=False):
        super().__init__(seed)
        self.shortlist_config = config or CWVShortlistConfig()
        if type(reuse_successors) is not bool:
            raise ValueError("reuse_successors must be boolean")
        if reuse_successors and self.shortlist_config.uniform:
            raise ValueError("successor reuse requires the learned shortlist")
        self.reuse_successors = reuse_successors
        self.last_successor_reuse = None
        if not self.shortlist_config.uniform and evaluator is None:
            raise ValueError("learned shortlist requires a complete-world evaluator")
        self.evaluator = evaluator
        self.N_DETERMINIZATIONS = self.shortlist_config.selection_worlds
        self.last_shortlist = None
        self.shortlist_counts = dict.fromkeys((
            "decisions", "forced", "legal_actions", "shortlisted_actions",
            "offballot_kept", "offballot_played", "cheap_worlds",
            "cheap_evaluations", "cheap_batches", "terminal_afterstates"), 0)
        self.shortlist_wall_seconds = 0.0

    def _means(self, rnd, seat, actions, worlds):
        """Score EVERY action/world, retaining only O(K + batch_size) state."""
        sums = np.zeros(len(actions), dtype=np.float64)
        pending, indices = [], []
        # The tensor cache spans this decision, not one world: the original
        # forward batches can straddle world boundaries. Exact leaf identity
        # keeps those worlds distinct without flushing/changing batch shapes.
        tensor_cache = TensorInputCache() if self.reuse_successors else None
        reuse = {"root_actions": 0, "leaf_hits": 0, "leaf_completions": 0,
                 "peak_entries": 0}

        def flush():
            if not pending:
                return
            scored = (self.evaluator.score(pending, seat) if tensor_cache is None
                      else self.evaluator.score(pending, seat, tensor_cache=tensor_cache))
            values = np.asarray(scored, dtype=np.float64)
            if values.shape != (len(pending),) or not np.isfinite(values).all():
                raise ValueError("CWV shortlist requires one finite root-team value per afterstate")
            np.add.at(sums, indices, values)
            self.shortlist_counts["cheap_evaluations"] += len(pending)
            self.shortlist_counts["cheap_batches"] += 1
            pending.clear()
            indices.clear()

        for hands, buried in worlds:
            successor_cache = (WorldSuccessorCache(rnd, seat, hands, buried)
                               if self.reuse_successors else None)
            for index, action in enumerate(actions):
                # Exactly the #229 convention: engine root action, heuristic
                # finishes this trick, then complete-world value (terminal exact).
                leaf = (afterstate(rnd, seat, hands, buried, action, finish_trick=True)
                        if successor_cache is None else successor_cache.leaf(action))
                self.shortlist_counts["terminal_afterstates"] += int(leaf.phase == "round_end")
                pending.append(leaf)
                indices.append(index)
                if len(pending) == self.shortlist_config.batch_size:
                    flush()
            if successor_cache is not None:
                for key in ("root_actions", "leaf_hits", "leaf_completions"):
                    reuse[key] += successor_cache.counters[key]
                reuse["peak_entries"] = max(reuse["peak_entries"], successor_cache.peak_entries)
        flush()
        self.last_successor_reuse = (None if tensor_cache is None else {
            "schema": "cwv-successor-reuse-v1", "max_entries_per_cache": 128,
            **reuse, "tensor_hits": tensor_cache.hits,
            "tensor_completions": tensor_cache.completions,
            "peak_tensor_entries": tensor_cache.peak_entries})
        return sums / len(worlds)

    def _candidates(self, rnd, seat):
        started = time.perf_counter()
        self.last_successor_reuse = None
        production = super()._candidates(rnd, seat)
        incumbent = tuple(sorted(production[0]))
        legal = enumerate_legal(rnd, seat, cap=None, must_include=production)
        actions = legal.actions
        keys = [tuple(sorted(a)) for a in actions]
        # cap=None exhausts the iterator even if the separate counting helper
        # declines a >2M raw-candidate count. Never use a capped prefix.
        if (not keys or len(set(keys)) != len(keys) or incumbent not in keys
                or (legal.count is not None and legal.count != len(keys))):
            raise ValueError("CWV shortlist exhaustive legal population drift")
        base = keys.index(incumbent)
        alternatives = [i for i in range(len(keys)) if i != base]
        state = self.rng.getstate()
        world_seed = _child_seed(state, "cwv-full-legal-worlds-v1")
        uniform_seed = _child_seed(state, "cwv-full-legal-uniform-v1")
        means = None
        before = dict(self.shortlist_counts)
        sampler_before = self._sampler_snapshot()
        if len(actions) == 1:
            chosen = []
            self.shortlist_counts["forced"] += 1
        elif self.shortlist_config.uniform:
            chosen = random.Random(uniform_seed).sample(
                alternatives, min(len(alternatives), self.shortlist_config.alternatives))
        else:
            parent_rng = self.rng
            try:
                self.rng = random.Random(world_seed)
                worlds, _ = sample_worlds(self, rnd, seat, self.shortlist_config.worlds)
            finally:
                # Cheap ranking cannot consume production selection/report RNG.
                self.rng = parent_rng
            if len(worlds) != self.shortlist_config.worlds:
                raise ValueError("CWV shortlist cheap world population underfilled")
            self.shortlist_counts["cheap_worlds"] += len(worlds)
            means = self._means(rnd, seat, actions, worlds)
            chosen = sorted(alternatives, key=lambda i: (-means[i], keys[i]))[
                :self.shortlist_config.alternatives]
        selected = [base, *chosen]
        production_keys = {tuple(sorted(a)) for a in production}
        kept = [actions[i] for i in selected]
        self.shortlist_counts["decisions"] += 1
        self.shortlist_counts["legal_actions"] += len(actions)
        self.shortlist_counts["shortlisted_actions"] += len(selected)
        self.shortlist_counts["offballot_kept"] += sum(keys[i] not in production_keys for i in selected)
        self.last_shortlist = {
            "config": asdict(self.shortlist_config), "complete": True,
            "legal_count": len(actions), "production_count": len(production),
            "legal_sha256": hashlib.sha256(json.dumps(keys, separators=(",", ":")).encode()).hexdigest(),
            "incumbent": list(incumbent), "shortlist": kept,
            "shortlist_indices": selected,
            "shortlist_means": None if means is None else [float(means[i]) for i in selected],
            "production_keys": sorted(production_keys),
            "world_seed": world_seed, "uniform_seed": uniform_seed,
            "cheap_sampler_delta": self._sampler_delta(sampler_before),
            "counts": {k: self.shortlist_counts[k] - before[k] for k in before},
        }
        if self.reuse_successors:
            self.last_shortlist["successor_reuse"] = self.last_successor_reuse
        elapsed = time.perf_counter() - started
        self.shortlist_wall_seconds += elapsed
        self.last_shortlist["wall_seconds"] = elapsed
        return kept

    def decide_play(self, rnd, seat):
        self.last_shortlist = None
        played = super().decide_play(rnd, seat)
        detail = self.last_shortlist
        if detail is not None:
            offballot = tuple(sorted(played)) not in set(detail["production_keys"])
            self.shortlist_counts["offballot_played"] += int(offballot)
            detail["offballot_played"] = offballot
            if self.last_decision_record is not None:
                self.last_decision_record["cwv_shortlist"] = detail
                # The inherited snapshot intentionally covers the entire
                # decision, including candidate generation. Keep that truthful
                # total AND distinguish production's selection/report samples.
                total = self.last_decision_record["sampler_counters"]["delta"]
                detail["production_sampler_delta"] = {
                    key: value - detail["cheap_sampler_delta"][key]
                    for key, value in total.items()}
        return played


# ------------------------------------------------------- registry entry point
#
# `cwv_shortlist_screen.make_side` builds this bot directly; so do the probes
# and the cost script.  Nothing registered it, so `registry.make_bot` -- and
# therefore `harvest/trajectory.py --policy` -- could not reach it.  The
# construction below is that screen's, verbatim: checkpoint -> evaluator ->
# `CWVShortlistBot(evaluator, **kwargs)` -> `REPORT_FOLD_WORLDS`.
#
# DO NOT reach for `registry.register_cwv_policies` here.  It registers
# `mc-cwv-<ckpt8>-w32`, which resolves to the ONE-PLY bot `CWVOnePly_w32`: a
# different design that LOSES on the scorecard (-0.11 to -0.14).  Generating
# expert-iteration data with it would look healthy for sixteen hours and be
# worse than production.  Hence the distinct `mc-shortlist-` prefix and the
# type refusal in `_require_shortlist`.

#: the screened W32 recipe (`cwv_shortlist_screen`'s learned arm)
SHORTLIST_WORLDS = 32
SHORTLIST_ALTERNATIVES = 4
SHORTLIST_SELECTION_WORLDS = 30
SHORTLIST_REPORT_WORLDS = 300
SHORTLIST_BATCH_SIZE = 128
SHORTLIST_ENCODING = "mlp-static"
SHORTLIST_REUSE_SUCCESSORS = True

#: env registration, in the style of `SHENGJI_CWV_*` / `SHENGJI_NETROLL_*`
SHORTLIST_ENV_CKPT = "SHENGJI_CWV_SHORTLIST_CKPT"


class ShortlistPolicyError(RuntimeError):
    """A shortlist policy name did not build the shortlist bot."""


#: Every knob that changes what the shortlist bot DOES. The policy name binds
#: all of them, because the name is what a run receipt, a seed window and a
#: resume key on: if two recipes could share a name, a resume would accept data
#: generated under a different search than the one it is continuing.
RECIPE_FIELDS = ("alternatives", "selection_worlds", "report_worlds",
                 "batch_size", "encoding", "reuse_successors")


def resolved_recipe(**recipe) -> dict:
    """The recipe with every field present and normalised, or a refusal.

    Refusing an unknown field is the point: a knob added to the bot without
    being added to ``RECIPE_FIELDS`` would otherwise change behaviour while
    leaving the identity untouched, which is exactly the hole this closes.
    """
    unknown = set(recipe) - set(RECIPE_FIELDS)
    if unknown:
        raise ValueError(
            f"recipe fields {sorted(unknown)} are not in RECIPE_FIELDS; add them "
            "there so the policy name binds them, or they will not reach the identity")
    defaults = {"alternatives": SHORTLIST_ALTERNATIVES,
                "selection_worlds": SHORTLIST_SELECTION_WORLDS,
                "report_worlds": SHORTLIST_REPORT_WORLDS,
                "batch_size": SHORTLIST_BATCH_SIZE,
                "encoding": SHORTLIST_ENCODING,
                "reuse_successors": SHORTLIST_REUSE_SUCCESSORS}
    out = {}
    for field in RECIPE_FIELDS:
        value = recipe.get(field, defaults[field])
        if field == "encoding":
            out[field] = str(value)
        elif field == "reuse_successors":
            out[field] = bool(value)
        else:
            out[field] = int(value)
    return out


def recipe_digest(worlds: int, recipe: dict) -> str:
    """Eight hex chars over the RESOLVED recipe and width, order-independent."""
    payload = json.dumps({"worlds": int(worlds), **resolved_recipe(**recipe)},
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]


def shortlist_policy_name(ckpt8: str, worlds: int = SHORTLIST_WORLDS, *,
                          recipe: dict) -> str:
    """``mc-shortlist-<ckpt8>-w<W>-r<recipe8>``.

    Deliberately unlike `cwv_policy.policy_name`'s ``mc-cwv-<ckpt8>-w<W>``:
    the two designs must never be confused by eye in a run receipt.

    ``recipe`` is REQUIRED and keyword-only on purpose. An earlier version of
    this function took the checkpoint and width alone, so K4 and K8 resolved to
    one name while building genuinely different bots -- a resume accepted the
    wrong search silently. Making the argument impossible to omit is what stops
    that returning.
    """
    return (f"mc-shortlist-{ckpt8}-w{int(worlds)}"
            f"-r{recipe_digest(worlds, recipe)}")


def _build_shortlist(evaluator, *, seed, config, reuse_successors):
    """The one construction site, so the guard below has something to guard."""
    return CWVShortlistBot(evaluator, seed=seed, config=config,
                           reuse_successors=reuse_successors)


def _require_shortlist(bot, name: str):
    """REFUSE anything that is not the shortlist bot (the one-ply trap)."""
    if not isinstance(bot, CWVShortlistBot):
        raise ShortlistPolicyError(
            f"policy {name!r} built {type(bot).__name__}, not CWVShortlistBot. "
            "The one-ply CWV bot (mc-cwv-<ckpt8>-w32 / CWVOnePly_w32) is a "
            "different design that loses on the scorecard; refusing to "
            "generate data with it under a shortlist name.")
    return bot


def make_shortlist_bot(checkpoint, *, seed=None,
                       worlds: int = SHORTLIST_WORLDS,
                       alternatives: int = SHORTLIST_ALTERNATIVES,
                       selection_worlds: int = SHORTLIST_SELECTION_WORLDS,
                       report_worlds: int = SHORTLIST_REPORT_WORLDS,
                       batch_size: int = SHORTLIST_BATCH_SIZE,
                       encoding: str = SHORTLIST_ENCODING,
                       reuse_successors: bool = SHORTLIST_REUSE_SUCCESSORS,
                       threads: int | None = 1,
                       name: str | None = None) -> "CWVShortlistBot":
    """`cwv_shortlist_screen.make_side`'s learned arm, built by checkpoint.

    The evaluator picks the tensor builder for the CHECKPOINT's own
    ``enc_version`` and applies the static adapter only while the net really
    is an MLP (`CompleteWorldEvaluator.encoder` / ``effective_encoding``), so
    ``encoding='mlp-static'`` is a request, never an override of the
    checkpoint's identity.
    """
    from ..ai.cwv_policy import shared_evaluator

    evaluator = shared_evaluator(checkpoint, threads=threads,
                                 max_batch=int(batch_size), encoding=encoding)
    config = CWVShortlistConfig(worlds=int(worlds),
                                selection_worlds=int(selection_worlds),
                                alternatives=int(alternatives),
                                batch_size=int(batch_size), uniform=False)
    bot = _build_shortlist(evaluator, seed=seed, config=config,
                           reuse_successors=bool(reuse_successors))
    _require_shortlist(bot, name or shortlist_policy_name(
        evaluator.ckpt8 or "unknown", worlds))
    bot.REPORT_FOLD_WORLDS = int(report_worlds)
    bot.cwv_checkpoint_sha256 = evaluator.checkpoint_sha256
    bot.cwv_ckpt8 = evaluator.ckpt8
    bot.cwv_enc_version = evaluator.enc_version
    bot.cwv_encoding = evaluator.effective_encoding
    return bot


def shortlist_registry_entries(checkpoint, worlds=(SHORTLIST_WORLDS,),
                               **recipe) -> dict:
    """``{name: factory}`` for every W, named by the VALUE checkpoint.

    Same identity rule as `cwv_registry_entries`: the checkpoint IS the
    policy, so every name embeds ``<ckpt8>`` and a bare ``mc-shortlist``
    never exists.  The checkpoint is hashed here (the name must be stable)
    and LOADED lazily, once per process, on the first `make_bot`.
    """
    from ..ai.cwv_policy import checkpoint_id

    ckpt8 = checkpoint_id(checkpoint)
    entries = {}

    def factory(name: str, w: int):
        def make(**kw):
            return make_shortlist_bot(checkpoint, seed=kw.get("seed"),
                                      worlds=w, name=name, **recipe)
        return make

    for w in sorted({int(w) for w in worlds}):
        if w < 1:
            raise ValueError("shortlist worlds must be positive")
        name = shortlist_policy_name(ckpt8, w, recipe=recipe)
        entries[name] = factory(name, w)
    return entries


def shortlist_env_recipe(environ=None) -> tuple[str, list[int], dict] | None:
    """``(checkpoint, worlds, recipe)`` described by ``SHENGJI_CWV_SHORTLIST_*``.

    SHENGJI_CWV_SHORTLIST_CKPT              checkpoint path (required)
    SHENGJI_CWV_SHORTLIST_WORLDS            comma list of W (default 32)
    SHENGJI_CWV_SHORTLIST_ALTERNATIVES      default 4
    SHENGJI_CWV_SHORTLIST_SELECTION_WORLDS  default 30
    SHENGJI_CWV_SHORTLIST_REPORT_WORLDS     default 300
    SHENGJI_CWV_SHORTLIST_BATCH_SIZE        default 128
    SHENGJI_CWV_SHORTLIST_ENCODING          default mlp-static
    SHENGJI_CWV_SHORTLIST_REUSE_SUCCESSORS  1/0, default 1
    """
    import os as _os

    env = _os.environ if environ is None else environ
    checkpoint = env.get(SHORTLIST_ENV_CKPT)
    if not checkpoint:
        return None
    worlds = [int(part) for part
              in env.get("SHENGJI_CWV_SHORTLIST_WORLDS",
                         str(SHORTLIST_WORLDS)).split(",") if part]
    recipe = {
        "alternatives": int(env.get("SHENGJI_CWV_SHORTLIST_ALTERNATIVES",
                                    SHORTLIST_ALTERNATIVES)),
        "selection_worlds": int(env.get("SHENGJI_CWV_SHORTLIST_SELECTION_WORLDS",
                                        SHORTLIST_SELECTION_WORLDS)),
        "report_worlds": int(env.get("SHENGJI_CWV_SHORTLIST_REPORT_WORLDS",
                                     SHORTLIST_REPORT_WORLDS)),
        "batch_size": int(env.get("SHENGJI_CWV_SHORTLIST_BATCH_SIZE",
                                  SHORTLIST_BATCH_SIZE)),
        "encoding": env.get("SHENGJI_CWV_SHORTLIST_ENCODING", SHORTLIST_ENCODING),
        "reuse_successors": env.get("SHENGJI_CWV_SHORTLIST_REUSE_SUCCESSORS", "1")
        not in ("0", "false", "no", ""),
    }
    return checkpoint, (worlds or [SHORTLIST_WORLDS]), recipe


# ``registry`` registers the env-driven shortlist policy at ITS import, but when
# this module is the one imported first it is only partway through its own body
# at that moment and the helper below does not exist yet.  Registration is
# idempotent (``REGISTRY.update``), so drive it again from here, where every
# definition is in place.  Together the two call sites make the registration
# independent of which module a caller reaches first.
from ..ai.registry import _register_cwv_shortlist_from_env as _register_from_env

_register_from_env()
