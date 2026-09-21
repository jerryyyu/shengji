"""Production wrapper for the policy/value search (the ``pv-search`` bot mode).

The search itself is `policy_value_search.PolicyValueBot` (the screened design:
sample W worlds through production's sampler, let the policy head admit K
candidates with the heuristic anchor pinned, score every admitted action's
afterstate with the value head in every world, take the highest mean).  This
module adds only what serving needs and nothing that changes the decision:

* ONE NumPy package (``.npz``, the release-28 shape) serves both heads -- the
  value evaluator through `shared_evaluator` and the policy log-odds through
  `cwv_prior_admission.load_prior_checked`, both without Torch;
* a module-level predictor (`NumpyPriorPredict`) instead of the harness's
  inner adapter class, so the bot survives the server's per-turn
  ``copy.deepcopy`` of the whole bot (the release-25 failure mode);
* the encoder version threaded from the package (a v5 package fed v2 rows would
  fail at its first decision -- the width check in `prior_encoder_version`);
* a cooperative serving budget on card play, mirroring the shipped bury budget:
  the heuristic anchor is computed first, ``check_budget`` runs at every bounded
  boundary (between world draws and value batches), and on expiry or any search
  error the sampler's RNG is restored and the anchor is returned with a
  ``pv-search-fallback-v1`` record -- never a partial search result;
* a registry name that pins the recipe: ``pv-search-<ckpt8>-w<W>-k<K>-r<recipe8>``.

Declare and bury stay heuristic (`HeuristicBot`), exactly as in every screen
that measured this design (card play only; shared heuristic declare/bury).  The
value-guided hybrid bury of release 27/28 is NOT composed here; that is a
separate change with its own witness.  Nothing in this module deploys anything:
registration happens only when ``SHENGJI_PV_CKPT`` is set.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass

import numpy as np

from ..ai.cwv_policy import file_sha256, sample_worlds, shared_evaluator
from ..ai.heuristic import HeuristicBot
from ..ai.memory import Memory
from ..harvest.legal import enumerate_legal
from .cwv_prior_admission import (CWVPriorAdmissionBot, load_prior_checked,
                                  prior_encoder_version, root_clone)
from .policy_prior import flat_input, root_tensors
from .policy_value_search import PolicyValueBot

SCHEMA = "pv-search-recipe-v1"
RECORD_SCHEMA = "pv-search-decision-v1"
FALLBACK_SCHEMA = "pv-search-fallback-v1"
ENCODING = "mlp-static"
DEFAULTS = dict(worlds=64, candidates=8, cap=4000, batch_size=128, seed=0,
                serving_budget_seconds=None)
ENV_PREFIX = "SHENGJI_PV_"


class PVSearchPolicyError(RuntimeError):
    """The production wrapper refused to build or to run a decision."""


class PVSearchBudgetExceeded(PVSearchPolicyError):
    """The cooperative play budget expired at a bounded boundary."""


def _serving_budget(value):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError("serving_budget_seconds must be finite and positive")
    return float(value)


class NumpyPriorPredict:
    """The policy log-odds callable, as a plain importable object.

    Holds production's checked prior triple and dispatches through
    `CWVPriorAdmissionBot._prior_log_odds`, so every supported package kind
    behaves exactly as it does under prior admission.  Being a module-level
    class (not the harness's inner adapter) it deep-copies and pickles with the
    bot; the NumPy models themselves are deepcopy-safe and share their
    read-only weights.
    """

    def __init__(self, path: str, sha256: str):
        self.path, self.sha256 = str(path), str(sha256)
        self._prior_kind, self._prior_net, self._prior_payload = load_prior_checked(self.path, self.sha256)
        self.version = prior_encoder_version(self._prior_kind, self._prior_net, self._prior_payload)

    def __call__(self, X):
        return CWVPriorAdmissionBot._prior_log_odds(self, X)


@dataclass(frozen=True)
class PVSearchConfig:
    checkpoint_sha256: str
    worlds: int = DEFAULTS["worlds"]
    candidates: int = DEFAULTS["candidates"]
    cap: int = DEFAULTS["cap"]
    batch_size: int = DEFAULTS["batch_size"]
    serving_budget_seconds: float | None = DEFAULTS["serving_budget_seconds"]
    encoding: str = ENCODING
    schema: str = SCHEMA


def recipe_digest(config: PVSearchConfig) -> str:
    """``<recipe8>``: sha256 of the frozen recipe, the seed excluded (a seed is a
    run parameter, not a policy identity)."""
    encoded = json.dumps(asdict(config), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:8]


def pv_policy_name(ckpt8: str, config: PVSearchConfig) -> str:
    return f"pv-search-{ckpt8}-w{config.worlds}-k{config.candidates}-r{recipe_digest(config)}"


class PVSearchBot(PolicyValueBot):
    """`PolicyValueBot` on a NumPy package, with the serving budget and record."""

    def __init__(self, predict, *, evaluator, version: int, config: PVSearchConfig,
                 checkpoint: str, seed: int = 0):
        super().__init__(predict, evaluator=evaluator, candidates=config.candidates,
                         batch_size=config.batch_size, worlds=config.worlds,
                         cap=config.cap, seed=seed)
        self.version = int(version)
        self.config = config
        self.checkpoint = str(checkpoint)
        self.checkpoint_sha256 = config.checkpoint_sha256
        self.serving_budget_seconds = _serving_budget(config.serving_budget_seconds)
        self.seed = seed
        self.last_play_record = None

    # -- the two harness hooks that serving changes -------------------------

    def scores(self, rnd, seat, actions, worlds):
        """As the harness, with the package's encoder version threaded through."""
        from .policy_prior import CARD_INDEX, N_CARDS
        x = np.stack([flat_input(root_tensors(root_clone(rnd, hands, buried), seat, self.version),
                                 self.version)
                      for hands, buried in worlds]).astype(np.float32)
        logits = np.asarray(self.predict(x), dtype=np.float64)
        if logits.shape != (len(worlds), N_CARDS) or not np.isfinite(logits).all():
            raise ValueError("policy requires finite W x 54 log-odds")
        multiplicity = np.zeros((len(actions), N_CARDS), dtype=np.float64)
        for i, action in enumerate(actions):
            for card in action:
                multiplicity[i, CARD_INDEX[card]] += 1
        return logits @ multiplicity.T

    def _worlds(self, rnd, seat, check_budget=None):
        mem = Memory(rnd, seat, own_kitty=getattr(self.sampler, "BANKER_KITTY", True))
        worlds, attempts = sample_worlds(self.sampler, rnd, seat, self.worlds, mem=mem,
                                         check_budget=check_budget)
        if len(worlds) != self.worlds:
            raise PVSearchPolicyError(f"policy world sampling short: {len(worlds)}/{self.worlds}")
        if any(rnd.ordering.eff_suit(c) in mem.voids[s]
               for hands, _ in worlds for s in range(4) if s != seat for c in hands[s]):
            raise PVSearchPolicyError("policy world sampling violates public voids")
        return worlds, attempts

    def _value_means(self, rnd, seat, actions, worlds, check_budget=None):
        sums = np.zeros(len(actions), dtype=np.float64)
        pending, indices = [], []
        batches = 0

        def flush():
            nonlocal batches
            if not pending:
                return
            if check_budget is not None:
                check_budget()
            scores = np.asarray(self.evaluator.score(pending, seat), dtype=np.float64)
            if scores.shape != (len(pending),) or not np.isfinite(scores).all():
                raise ValueError("value evaluator requires one finite root-team score per leaf")
            np.add.at(sums, indices, scores)
            batches += 1
            pending.clear()
            indices.clear()

        for world_index, (hands, buried) in enumerate(worlds):
            for index, action in enumerate(actions):
                pending.append(self._leaf(rnd, seat, hands, buried, action, world_index))
                indices.append(index)
                if len(pending) == self.batch_size:
                    flush()
        flush()
        return sums / len(worlds), batches

    # -- the decision ---------------------------------------------------------

    def _search(self, rnd, seat, anchor, started, check_budget=None):
        legal = enumerate_legal(rnd, seat, cap=self.cap, must_include=[anchor])
        actions = list(legal.actions)
        worlds, attempts = self._worlds(rnd, seat, check_budget)
        if check_budget is not None:
            check_budget()
        preferences = self.scores(rnd, seat, actions, worlds).mean(axis=0)
        anchor_key = tuple(sorted(anchor))
        anchor_index = next(i for i, a in enumerate(actions) if tuple(sorted(a)) == anchor_key)
        ranked = sorted(range(len(actions)), key=lambda i: (-preferences[i], i))
        chosen = [anchor_index]
        chosen.extend(i for i in ranked if i != anchor_index)
        chosen = chosen[:self.candidates]
        admitted = [actions[i] for i in chosen]
        means, batches = self._value_means(rnd, seat, admitted, worlds, check_budget)
        winner = self._select(rnd, seat, admitted, means)
        self.last_decision_record = {
            "schema": RECORD_SCHEMA, "policy": getattr(self, "policy_name", None),
            "worlds": len(worlds), "sample_attempts": attempts, "actions": len(actions),
            "cap": self.cap, "legal_count": legal.count, "legal_complete": legal.complete,
            "admitted_indices": chosen, "value_means": means.tolist(),
            "selected_index": chosen[winner], "value_batches": batches,
            "value_evaluations": len(worlds) * len(admitted),
            "anchor_selected": winner == 0, "encoder_version": self.version,
            # ``played`` is the server's record/play contract (`api.server._log_play`)
            "played": list(admitted[winner]),
            "seconds": time.perf_counter() - started, "work_complete": True,
        }
        return list(admitted[winner])

    def decide_play(self, rnd, seat):
        self.last_decision_record = None
        started = time.perf_counter()
        anchor = HeuristicBot.decide_play(self, rnd, seat)
        if self.serving_budget_seconds is None:
            return self._search(rnd, seat, anchor, started)
        before = self.sampler.rng.getstate()

        def check_budget():
            if time.perf_counter() - started >= self.serving_budget_seconds:
                raise PVSearchBudgetExceeded("pv-search serving budget expired")

        try:
            return self._search(rnd, seat, anchor, started, check_budget)
        except Exception as exc:
            # Synchronous unwind, as the bury budget: no partial search result is
            # ever played; the sampler stream is restored so the next decision
            # draws exactly what it would have without the aborted search.
            # BaseException (cancellation/interrupt) is deliberately not caught.
            self.sampler.rng.setstate(before)
            self.last_decision_record = {
                "schema": FALLBACK_SCHEMA, "policy": getattr(self, "policy_name", None),
                "action": list(anchor), "played": list(anchor),
                "reason": "budget" if isinstance(exc, PVSearchBudgetExceeded) else "search-error",
                "error_class": type(exc).__name__,
                "budget_seconds": self.serving_budget_seconds,
                "elapsed_seconds": time.perf_counter() - started,
                "work_complete": False,
            }
            return list(anchor)


def _require_pv_search(bot, name: str):
    """REFUSE anything that is not the production wrapper under a pv-search name."""
    if not isinstance(bot, PVSearchBot):
        raise PVSearchPolicyError(f"policy {name!r} built {type(bot).__name__}, not PVSearchBot")
    return bot


def make_pv_search_bot(checkpoint: str, *, sha256: str, worlds: int = DEFAULTS["worlds"],
                       candidates: int = DEFAULTS["candidates"], cap: int = DEFAULTS["cap"],
                       batch_size: int = DEFAULTS["batch_size"], seed: int = DEFAULTS["seed"],
                       serving_budget_seconds=None, threads: int | None = 1,
                       name: str | None = None) -> PVSearchBot:
    """The served bot: one ``.npz`` package as value evaluator AND policy prior,
    hash-pinned, encoder version read from the package."""
    path = str(checkpoint)
    if not path.lower().endswith(".npz"):
        raise PVSearchPolicyError("pv-search serves a NumPy package (.npz); Torch checkpoints are not served")
    actual = file_sha256(path)
    if actual != sha256:
        raise PVSearchPolicyError(f"pv-search package SHA256 mismatch: {actual[:8]} != {sha256[:8]}")
    config = PVSearchConfig(checkpoint_sha256=sha256, worlds=int(worlds), candidates=int(candidates),
                            cap=int(cap), batch_size=int(batch_size),
                            serving_budget_seconds=_serving_budget(serving_budget_seconds))
    predict = NumpyPriorPredict(path, sha256)
    evaluator = shared_evaluator(path, threads=threads, max_batch=config.batch_size, encoding=ENCODING)
    if getattr(evaluator, "backend", None) != "numpy":
        raise PVSearchPolicyError("pv-search requires the numpy evaluator backend")
    bot = PVSearchBot(predict, evaluator=evaluator, version=predict.version, config=config,
                      checkpoint=path, seed=int(seed))
    if name is not None:
        bot.policy_name = name
    return bot


def pv_registry_entries(checkpoint: str, *, sha256: str, worlds: int = DEFAULTS["worlds"],
                        candidates: int = DEFAULTS["candidates"], cap: int = DEFAULTS["cap"],
                        batch_size: int = DEFAULTS["batch_size"], seed: int = DEFAULTS["seed"],
                        serving_budget_seconds=None) -> dict:
    """``{name: factory}`` for one recipe; the factory takes ``seed=`` from `make_bot`."""
    from ..ai.cwv_policy import checkpoint_id
    config = PVSearchConfig(checkpoint_sha256=sha256, worlds=int(worlds), candidates=int(candidates),
                            cap=int(cap), batch_size=int(batch_size),
                            serving_budget_seconds=_serving_budget(serving_budget_seconds))
    ckpt8 = checkpoint_id(checkpoint)
    if ckpt8 != sha256[:8]:
        raise PVSearchPolicyError(f"pv-search package on disk is {ckpt8}, bound SHA256 says {sha256[:8]}")
    name = pv_policy_name(ckpt8, config)

    def factory(**kw):
        return _require_pv_search(
            make_pv_search_bot(checkpoint, sha256=sha256, worlds=config.worlds,
                               candidates=config.candidates, cap=config.cap,
                               batch_size=config.batch_size, seed=int(kw.get("seed", seed)),
                               serving_budget_seconds=config.serving_budget_seconds, name=name),
            name)
    return {name: factory}


def pv_env_recipe(environ=None) -> dict:
    """``SHENGJI_PV_CKPT`` + ``_SHA256`` (both required: an unpinned package is refused)
    and the optional ``_WORLDS`` / ``_CANDIDATES`` / ``_CAP`` / ``_BATCH_SIZE`` / ``_SEED`` /
    ``_SERVING_BUDGET_SECONDS`` knobs, as keyword arguments for `pv_registry_entries`."""
    env = os.environ if environ is None else environ
    checkpoint = env.get(ENV_PREFIX + "CKPT")
    if not checkpoint:
        raise PVSearchPolicyError("SHENGJI_PV_CKPT is not set")
    sha256 = env.get(ENV_PREFIX + "SHA256")
    if not sha256 or len(sha256) != 64:
        raise PVSearchPolicyError("SHENGJI_PV_SHA256 must be the package's full sha256")
    recipe = dict(checkpoint=checkpoint, sha256=sha256)
    for key in ("worlds", "candidates", "cap", "batch_size", "seed"):
        raw = env.get(ENV_PREFIX + key.upper())
        if raw not in (None, ""):
            recipe[key] = int(raw)
    raw = env.get(ENV_PREFIX + "SERVING_BUDGET_SECONDS")
    if raw not in (None, ""):
        recipe["serving_budget_seconds"] = float(raw)
    return recipe
