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

Declare stays heuristic.  Bury is heuristic in `PVSearchBot` (as in every screen
that measured this design) and, in `PVSearchBuryBot`, the value-guided bury arms
of release 27/28 (`cwv_bury_policy.CWVBuryMixin`: heuristic / mc / hybrid) on the
same package's value head -- Jerry 2026-09-21: "we should use value guided hybrid".
Nothing in this module deploys anything: registration happens only when
``SHENGJI_PV_CKPT`` is set.
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
from .cwv_bury_policy import (_ARMS as BURY_ARMS, BuryPolicyError, CWVBuryConfig,
                              CWVBuryMixin, _serving_budget as _bury_budget)

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

    def __reduce__(self):
        # The NumPy models hold read-only MappingProxyType weights, which deep-copy
        # (the server's turn snapshot) but do not pickle (the screen's deadline
        # worker sends the bot state over IPC per move).  Pickle as the hash-pinned
        # (path, sha256) pair: unpickling reloads through `load_prior_checked`'s
        # per-process cache, so the model is identical and the hash is re-checked
        # in any process that has not seen it.
        return (NumpyPriorPredict, (self.path, self.sha256))


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
        # The screen's duel reads the production search-time counter off every side
        # (`oracle.screen.play_screen_round`: ``arm_search_secs``); accumulated wall
        # seconds of `decide_play`, as `MCBot.search_secs`.
        self.search_secs = 0.0

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
            if check_budget is not None:
                # post-score check: a batch that ran past the deadline must not
                # be published as complete work
                check_budget()

        for world_index, (hands, buried) in enumerate(worlds):
            for index, action in enumerate(actions):
                pending.append(self._leaf(rnd, seat, hands, buried, action, world_index))
                indices.append(index)
                if len(pending) == self.batch_size:
                    flush()
        flush()
        return sums / len(worlds), batches

    # -- the decision ---------------------------------------------------------

    # -- the two data-generation hooks (#592): the scored set and the admission -------
    # Serving never overrides them; a trajectory mixin widens the scored set with its
    # exploration draw and appends the draw to the admitted ballot, so the value head
    # prices it like any other candidate.

    def _legal(self, rnd, seat, must_include):
        """The scored set: the capped legal enumeration (``self.cap``, labelled by
        ``legal_complete``/``legal_count`` -- never exhaustive by assumption) with
        ``must_include`` forced in."""
        return enumerate_legal(rnd, seat, cap=self.cap, must_include=list(must_include))

    def _admit(self, rnd, seat, actions, preferences, anchor_index):
        """Indices (into ``actions``) the value head prices: the anchor first, then the
        policy's best scores, ``self.candidates`` in all."""
        ranked = sorted(range(len(actions)), key=lambda i: (-preferences[i], i))
        chosen = [anchor_index]
        chosen.extend(i for i in ranked if i != anchor_index)
        return chosen[:self.candidates]

    def _search(self, rnd, seat, anchor, started, check_budget=None):
        legal = self._legal(rnd, seat, [anchor])
        actions = list(legal.actions)
        worlds, attempts = self._worlds(rnd, seat, check_budget)
        if check_budget is not None:
            check_budget()
        preferences = self.scores(rnd, seat, actions, worlds).mean(axis=0)
        anchor_key = tuple(sorted(anchor))
        anchor_index = next(i for i, a in enumerate(actions) if tuple(sorted(a)) == anchor_key)
        chosen = [int(i) for i in self._admit(rnd, seat, actions, preferences, anchor_index)]
        if not chosen or chosen[0] != anchor_index or len(set(chosen)) != len(chosen) \
                or any(not 0 <= i < len(actions) for i in chosen):
            raise PVSearchPolicyError("admission must return distinct indices into the scored set, anchor first")
        admitted = [actions[i] for i in chosen]
        means, batches = self._value_means(rnd, seat, admitted, worlds, check_budget)
        if check_budget is not None:
            check_budget()   # pre-success: nothing past the deadline is published
        winner = self._select(rnd, seat, admitted, means)
        self.last_decision_record = {
            "schema": RECORD_SCHEMA, "policy": getattr(self, "policy_name", None),
            "worlds": len(worlds), "sample_attempts": attempts, "actions": len(actions),
            "cap": self.cap, "legal_count": legal.count, "legal_complete": legal.complete,
            "admitted_indices": chosen, "value_means": means.tolist(),
            # the admitted candidates' cards in admission order (played_index in a
            # trajectory record = admitted_indices.index(selected_index), never the
            # legal index), their policy log-odds, and the log-odds of the scored set's
            # first entries -- the harvester's bounded listing is the same enumeration
            # order (its cap 256 <= this cap), so the two align by position
            "admitted": [list(a) for a in admitted],
            "policy_log_odds_admitted": [float(preferences[i]) for i in chosen],
            "policy_log_odds_listing": [float(v) for v in preferences[:min(len(actions), 256)]],
            "selected_index": chosen[winner], "value_batches": batches,
            "value_evaluations": len(worlds) * len(admitted),
            "anchor_selected": winner == 0, "encoder_version": self.version,
            # ``played`` is the server's record/play contract (`api.server._log_play`)
            "played": list(admitted[winner]),
            "seconds": time.perf_counter() - started, "work_complete": True,
        }
        return list(admitted[winner])

    def decide_play(self, rnd, seat):
        started = time.perf_counter()
        try:
            return self._decide_play(rnd, seat, started)
        finally:
            self.search_secs += time.perf_counter() - started

    def _decide_play(self, rnd, seat, started):
        self.last_decision_record = None
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


class PVSearchBuryBot(CWVBuryMixin, PVSearchBot):
    """`PVSearchBot` with a DEV bury arm from `CWVBuryMixin` (release 27/28's
    value-guided bury on this package's value head).  The bury budget is its own
    knob, separate from the play budget; the fallback restores the play sampler's
    RNG, the only stream this bot owns."""

    def __init__(self, predict, *, evaluator, version: int, config: PVSearchConfig,
                 checkpoint: str, seed: int = 0, bury_arm: str = "hybrid",
                 bury_config: CWVBuryConfig | None = None, bury_serving_budget_seconds=None):
        if bury_arm not in BURY_ARMS:
            raise BuryPolicyError(f"unknown bury arm {bury_arm!r}")
        super().__init__(predict, evaluator=evaluator, version=version, config=config,
                         checkpoint=checkpoint, seed=seed)
        self.bury_arm = bury_arm
        self.bury_config = CWVBuryConfig() if bury_config is None else bury_config
        if not isinstance(self.bury_config, CWVBuryConfig):
            raise TypeError("bury_config must be a CWVBuryConfig")
        self.bury_serving_budget_seconds = _bury_budget(bury_serving_budget_seconds)
        self.last_bury_record = None

    def _bury_rng(self):
        return self.sampler.rng


def _require_pv_search(bot, name: str):
    """REFUSE anything that is not the production wrapper under a pv-search name."""
    if not isinstance(bot, PVSearchBot):
        raise PVSearchPolicyError(f"policy {name!r} built {type(bot).__name__}, not PVSearchBot")
    return bot


def make_pv_search_bot(checkpoint: str, *, sha256: str, worlds: int = DEFAULTS["worlds"],
                       candidates: int = DEFAULTS["candidates"], cap: int = DEFAULTS["cap"],
                       batch_size: int = DEFAULTS["batch_size"], seed: int = DEFAULTS["seed"],
                       serving_budget_seconds=None, threads: int | None = 1,
                       name: str | None = None, bury_arm: str | None = None,
                       bury_config: CWVBuryConfig | None = None,
                       bury_serving_budget_seconds=None) -> PVSearchBot:
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
    if bury_arm is None:
        bot = PVSearchBot(predict, evaluator=evaluator, version=predict.version, config=config,
                          checkpoint=path, seed=int(seed))
    else:
        bot = PVSearchBuryBot(predict, evaluator=evaluator, version=predict.version, config=config,
                              checkpoint=path, seed=int(seed), bury_arm=bury_arm,
                              bury_config=bury_config,
                              bury_serving_budget_seconds=bury_serving_budget_seconds)
    if name is not None:
        bot.policy_name = name
    return bot


def pv_registry_entries(checkpoint: str, *, sha256: str, worlds: int = DEFAULTS["worlds"],
                        candidates: int = DEFAULTS["candidates"], cap: int = DEFAULTS["cap"],
                        batch_size: int = DEFAULTS["batch_size"], seed: int = DEFAULTS["seed"],
                        serving_budget_seconds=None, bury_arm: str | None = None,
                        bury_config: CWVBuryConfig | None = None,
                        bury_serving_budget_seconds=None) -> dict:
    """``{name: factory}`` for one recipe; the factory takes ``seed=`` from `make_bot`.
    With ``bury_arm`` the name carries the bury identity exactly as the shortlist's
    bury wrapper does: ``<play name>-bury-<arm>-<12 hex of the cwv-bury-recipe-v1 identity>``."""
    from ..ai.cwv_policy import checkpoint_id
    config = PVSearchConfig(checkpoint_sha256=sha256, worlds=int(worlds), candidates=int(candidates),
                            cap=int(cap), batch_size=int(batch_size),
                            serving_budget_seconds=_serving_budget(serving_budget_seconds))
    ckpt8 = checkpoint_id(checkpoint)
    if ckpt8 != sha256[:8]:
        raise PVSearchPolicyError(f"pv-search package on disk is {ckpt8}, bound SHA256 says {sha256[:8]}")
    name = pv_policy_name(ckpt8, config)
    bury_identity = None
    if bury_arm is not None:
        if bury_arm not in BURY_ARMS:
            raise BuryPolicyError(f"unknown bury arm {bury_arm!r}")
        bconfig = CWVBuryConfig() if bury_config is None else bury_config
        if type(bconfig) is not CWVBuryConfig:
            raise TypeError("bury_config must be a CWVBuryConfig")
        bbudget = _bury_budget(bury_serving_budget_seconds)
        bury_identity = {"schema": "cwv-bury-recipe-v1", "play_policy": name,
                         "checkpoint_sha256": sha256, "arm": bury_arm,
                         "config": asdict(bconfig), "fallback": "raise"}
        if bbudget is not None:
            bury_identity.update(fallback="heuristic-on-error-or-budget", serving_budget_seconds=bbudget)
        encoded = json.dumps(bury_identity, sort_keys=True, separators=(",", ":")).encode()
        name = f"{name}-bury-{bury_arm}-{hashlib.sha256(encoded).hexdigest()[:12]}"
        bury_config, bury_serving_budget_seconds = bconfig, bbudget

    def factory(**kw):
        bot = _require_pv_search(
            make_pv_search_bot(checkpoint, sha256=sha256, worlds=config.worlds,
                               candidates=config.candidates, cap=config.cap,
                               batch_size=config.batch_size, seed=int(kw.get("seed", seed)),
                               serving_budget_seconds=config.serving_budget_seconds, name=name,
                               bury_arm=bury_arm, bury_config=bury_config,
                               bury_serving_budget_seconds=bury_serving_budget_seconds),
            name)
        if bury_identity is not None:
            if not isinstance(bot, PVSearchBuryBot):
                raise PVSearchPolicyError(f"policy {name!r} built {type(bot).__name__}, not PVSearchBuryBot")
            bot.bury_recipe_identity = {**bury_identity, "config": dict(bury_identity["config"])}
        return bot
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
    arm = env.get(ENV_PREFIX + "BURY_ARM")
    if arm:
        if arm not in BURY_ARMS:
            raise PVSearchPolicyError(f"unknown bury arm {arm!r}")
        values = asdict(CWVBuryConfig())
        for key in values:
            raw = env.get(ENV_PREFIX + "BURY_" + key.upper())
            if raw not in (None, ""):
                values[key] = int(raw)
        recipe["bury_arm"] = arm
        recipe["bury_config"] = CWVBuryConfig(**values)
        raw = env.get(ENV_PREFIX + "BURY_SERVING_BUDGET_SECONDS")
        if raw not in (None, ""):
            recipe["bury_serving_budget_seconds"] = float(raw)
    return recipe
