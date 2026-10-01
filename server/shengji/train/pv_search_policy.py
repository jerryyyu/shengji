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

Optional admission rules (#676 A/C, #677 strategy 1), BOTH OFF BY DEFAULT:
``SHENGJI_PV_ADMISSION_DIVERSITY=1`` caps near-duplicate throws in the K-1
policy slots and ``SHENGJI_PV_ADMIT_FORCED_SINGLE=1`` also admits, next to an
admitted throw, the component the engine would force in most sampled worlds
(definitions and defaults: `policy_value_search`).  Each accepts only ``0`` or
``1``.  A rule that is on enters the recipe digest and adds ``-div`` / ``-fs``
to the registry name before ``-r<recipe8>``; with both off the recipe payload,
the digest, the name (production:
``pv-search-491ee4bf-w64-k8-r4a09aef5-bury-hybrid-355958b4db25``) and the
admitted indices are exactly what they were before the rules existed.

Optional sampler rule (#676 B, the repeated doomed throws), OFF BY DEFAULT:
``SHENGJI_PV_REFUSAL_CONSTRAINTS=1`` makes the world sampler honour every
failed-throw notice posted this round (`ai.refusal`: a sampled world must make
the refused throw refusable, with the same forced component, under the real
``validate_lead``; the thrower's unplayed attempted cards are pinned to it).
It accepts only ``0`` or ``1``.  On, it enters the recipe digest and adds
``-rc`` to the registry name before ``-r<recipe8>``; off, the recipe payload,
the digest, the name (production:
``pv-search-491ee4bf-w64-k8-r4a09aef5-bury-hybrid-355958b4db25``), the sampled
worlds and the decision record are exactly what they were before the rule
existed.  The encoder and its hashed source closure are untouched.
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
from ..ai.refusal import RefusalLedger, sample_worlds_refusal_aware
from ..harvest.legal import enumerate_legal
from .cwv_prior_admission import (CWVPriorAdmissionBot, load_prior_checked,
                                  prior_encoder_version, root_clone)
from .policy_value_search import ADMISSION_DEFAULTS, FORCED_EXTRA_SLOTS, PolicyValueBot
from .cwv_bury_policy import (_ARMS as BURY_ARMS, BuryPolicyError, CWVBuryConfig,
                              CWVBuryMixin, _serving_budget as _bury_budget)

SCHEMA = "pv-search-recipe-v1"
RECORD_SCHEMA = "pv-search-decision-v1"
FALLBACK_SCHEMA = "pv-search-fallback-v1"
ENCODING = "mlp-static"
DEFAULTS = dict(worlds=64, candidates=8, cap=4000, batch_size=128, seed=0,
                serving_budget_seconds=None)
#: the optional admission rules (`policy_value_search`): env flag -> recipe key
ADMISSION_RULES = {"ADMISSION_DIVERSITY": "admission_diversity",
                   "ADMIT_FORCED_SINGLE": "admit_forced_single"}
#: name tokens, in name order, for the rules that are on
ADMISSION_TOKENS = (("admission_diversity", "div"), ("admit_forced_single", "fs"))
#: the optional sampler rule (`ai.refusal`): env flag -> recipe key, and its default
SAMPLER_RULES = {"REFUSAL_CONSTRAINTS": "refusal_constraints"}
SAMPLER_DEFAULTS = dict(refusal_constraints=False)
#: name tokens, in name order, for the rules that are on
SAMPLER_TOKENS = (("refusal_constraints", "rc"),)
#: every optional rule, env flag -> recipe key, and the name tokens in name
#: order (admission rules first, then the sampler rule): div, fs, rc
RULES = {**ADMISSION_RULES, **SAMPLER_RULES}
RULE_TOKENS = ADMISSION_TOKENS + SAMPLER_TOKENS
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
    # the optional admission rules (#676 A/C) and the sampler rule (#676 B); OFF by
    # default and, while off, ABSENT from the recipe payload so every pre-existing
    # name is unchanged
    admission_diversity: bool = ADMISSION_DEFAULTS["admission_diversity"]
    admit_forced_single: bool = ADMISSION_DEFAULTS["admit_forced_single"]
    refusal_constraints: bool = SAMPLER_DEFAULTS["refusal_constraints"]


def recipe_payload(config: PVSearchConfig) -> dict:
    """The digested recipe: every field, except that a rule that is OFF is
    omitted (the payload of the pre-rule recipe, byte for byte) and an admission
    rule that is on carries its parameters."""
    payload = asdict(config)
    for key in RULES.values():
        if type(payload[key]) is not bool:
            raise PVSearchPolicyError(f"{key} must be a bool")
        if not payload[key]:
            del payload[key]
    if config.admission_diversity:
        payload["max_per_structure"] = ADMISSION_DEFAULTS["max_per_structure"]
    if config.admit_forced_single:
        payload["forced_min_fraction"] = ADMISSION_DEFAULTS["forced_min_fraction"]
    return payload


def recipe_digest(config: PVSearchConfig) -> str:
    """``<recipe8>``: sha256 of the frozen recipe, the seed excluded (a seed is a
    run parameter, not a policy identity)."""
    encoded = json.dumps(recipe_payload(config), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:8]


def pv_policy_name(ckpt8: str, config: PVSearchConfig, prior8: str | None = None) -> str:
    """``pv-search-<value pkg>-w..``; with a SEPARATE prior package (#663 step 2: a policy
    scorer swapped while the value evaluator stays fixed) the name also carries the
    prior's id, so the two identities can never be mistaken for one package."""
    prior = f"-prior-{prior8}" if prior8 else ""
    rules = "".join(f"-{token}" for field, token in RULE_TOKENS if getattr(config, field))
    return (f"pv-search-{ckpt8}{prior}-w{config.worlds}-k{config.candidates}{rules}"
            f"-r{recipe_digest(config)}")


class PVSearchBot(PolicyValueBot):
    """`PolicyValueBot` on a NumPy package, with the serving budget and record."""

    def __init__(self, predict, *, evaluator, version: int, config: PVSearchConfig,
                 checkpoint: str, seed: int = 0):
        super().__init__(predict, evaluator=evaluator, candidates=config.candidates,
                         batch_size=config.batch_size, worlds=config.worlds,
                         cap=config.cap, seed=seed,
                         admission_diversity=config.admission_diversity,
                         admit_forced_single=config.admit_forced_single)
        self.version = int(version)
        self.config = config
        self.checkpoint = str(checkpoint)
        self.checkpoint_sha256 = config.checkpoint_sha256
        self.serving_budget_seconds = _serving_budget(config.serving_budget_seconds)
        self.seed = seed
        self.last_play_record = None
        # the optional sampler rule (#676 B): the round's failed-throw notices, as
        # seen on this bot's turns, constrain its sampled worlds (`ai.refusal`)
        self.refusal_constraints = bool(config.refusal_constraints)
        self._refusals = RefusalLedger()
        self._last_sampling = {}
        # The screen's duel reads the production search-time counter off every side
        # (`oracle.screen.play_screen_round`: ``arm_search_secs``); accumulated wall
        # seconds of `decide_play`, as `MCBot.search_secs`.
        self.search_secs = 0.0

    # -- the two harness hooks that serving changes -------------------------

    def scores(self, rnd, seat, actions, worlds):
        """As the harness, with the package's encoder version threaded through."""
        # lazy: policy_prior -> harvest.rebuild -> registry -> (env registration) -> this module
        # is a cycle when the rows extractor is imported first with SHENGJI_PV_* set
        from .policy_prior import CARD_INDEX, N_CARDS, flat_input, root_tensors
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
        self._last_sampling = {}
        refusals = self._refusals.observe(rnd) if self.refusal_constraints else ()
        if refusals:
            worlds, attempts, self._last_sampling = sample_worlds_refusal_aware(
                self.sampler, rnd, seat, self.worlds, refusals, mem=mem,
                check_budget=check_budget)
        else:
            # the rule off, or on with no refusal this round: production's draw,
            # unchanged (the same stream, the same worlds for the same seed)
            worlds, attempts = sample_worlds(self.sampler, rnd, seat, self.worlds, mem=mem,
                                             check_budget=check_budget)
        if len(worlds) != self.worlds:
            raise PVSearchPolicyError(f"policy world sampling short: {len(worlds)}/{self.worlds}")
        if any(rnd.ordering.eff_suit(c) in mem.voids[s]
               for hands, _ in worlds for s in range(4) if s != seat for c in hands[s]):
            raise PVSearchPolicyError("policy world sampling violates public voids")
        return worlds, attempts

    def _score_leaves(self, rnd, seat, actions, worlds, check_budget=None, capture=None):
        """The ONE scoring and batching loop; serving's accumulator, unchanged.

        ``capture``, when given, is a (worlds x actions) array whose cells are
        filled with the same leaf scores the accumulator receives.  It is purely
        additive: the sequential ``np.add.at`` accumulation, the batch
        boundaries, the evaluator call order and both budget checks are exactly
        what they were before this method existed, so a diagnostic that needs
        per-world values cannot alter what serving computes (Codex, #625).

        Default serving passes ``capture=None`` and allocates no matrix.
        """
        sums = np.zeros(len(actions), dtype=np.float64)
        pending, indices = [], []
        cells = [] if capture is not None else None
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
            if cells is not None:
                for (world_index, index), score in zip(cells, scores):
                    capture[world_index, index] = score
                cells.clear()
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
                if cells is not None:
                    cells.append((world_index, index))
                if len(pending) == self.batch_size:
                    flush()
        flush()
        return sums, batches

    def _value_means(self, rnd, seat, actions, worlds, check_budget=None):
        sums, batches = self._score_leaves(rnd, seat, actions, worlds, check_budget)
        return sums / len(worlds), batches

    def value_matrix(self, rnd, seat, actions, worlds, check_budget=None):
        """``(matrix, sums, batches)`` for the exploitability probe (#625).

        ``matrix[w, a]`` is the value of action ``a`` in world ``w``; ``sums`` is
        serving's own accumulator over the same scores, so a control arm that
        claims served parity reduces with ``sums / len(worlds)`` rather than
        re-summing the matrix -- reordering a float sum changes its result, and
        near-ties are where that stops being cosmetic.

        Nothing calls this on a served path.
        """
        matrix = np.full((len(worlds), len(actions)), np.nan, dtype=np.float64)
        sums, batches = self._score_leaves(rnd, seat, actions, worlds, check_budget,
                                           capture=matrix)
        if not np.isfinite(matrix).all():
            raise PVSearchPolicyError("value matrix has unfilled cells")
        return matrix, sums, batches

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
        """Indices (into ``actions``) the value head prices -- the FINAL ballot: the
        anchor first, then the policy's best scores, ``self.candidates`` in all, then
        any forced-component extras -- the harness's own admission
        (`PolicyValueBot._admit`; the worlds and the deadline reach it through the
        admission context `_search` sets).  A wrapper that captures the ballot here
        (the trajectory mixin, a hook override) captures everything the value head
        will price."""
        return super()._admit(rnd, seat, actions, preferences, anchor_index)

    def _search(self, rnd, seat, anchor, started, check_budget=None):
        legal = self._legal(rnd, seat, [anchor])
        actions = list(legal.actions)
        worlds, attempts = self._worlds(rnd, seat, check_budget)
        if check_budget is not None:
            check_budget()
        preferences = self.scores(rnd, seat, actions, worlds).mean(axis=0)
        anchor_key = tuple(sorted(anchor))
        anchor_index = next(i for i, a in enumerate(actions) if tuple(sorted(a)) == anchor_key)
        chosen = self._admission(rnd, seat, actions, preferences, anchor_index, worlds, check_budget)
        if not chosen or chosen[0] != anchor_index or len(set(chosen)) != len(chosen) \
                or any(not 0 <= i < len(actions) for i in chosen):
            raise PVSearchPolicyError("admission must return distinct indices into the scored set, anchor first")
        # The candidate budget bounds what PRODUCTION admits (K plus the forced
        # extras).  The harvest mixin appends its exploration draw AFTER the
        # production ballot (keyed in ``_draw_keys``); on the data path there is
        # no serving budget and so no fallback, so counting the draw here raised
        # on a full ballot (#680 at f78ecbe1, found stacking #687).  Draws are
        # excluded from the count; everything else -- a hook override's extras
        # included -- is bounded.
        draw_keys = getattr(self, "_draw_keys", None) or ()
        budgeted = [i for i in chosen if tuple(sorted(actions[i])) not in draw_keys]
        if len(budgeted) > self.candidates + FORCED_EXTRA_SLOTS:
            raise PVSearchPolicyError("admission exceeded the candidate budget")
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
            **self._admission_record(),
            **self._sampler_record(),
        }
        return list(admitted[winner])

    def _sampler_record(self):
        """The refusal rule's fields for the decision record: present only while
        the rule is on (zeros when no refusal constrained this decision)."""
        if not self.refusal_constraints:
            return {}
        return {"refusal_observations": 0, "refusal_rejections": 0,
                "refusal_fallback_worlds": 0, "refusal_pinned_codes": 0,
                **self._last_sampling}

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
                       bury_serving_budget_seconds=None,
                       bot_factory=None, prior_checkpoint: str | None = None,
                       prior_sha256: str | None = None,
                       refusal_constraints: bool = SAMPLER_DEFAULTS["refusal_constraints"],
                       admission_diversity: bool = ADMISSION_DEFAULTS["admission_diversity"],
                       admit_forced_single: bool = ADMISSION_DEFAULTS["admit_forced_single"]
                       ) -> PVSearchBot:
    """The served bot: one ``.npz`` package as value evaluator AND policy prior,
    hash-pinned, encoder version read from the package.

    ``prior_checkpoint`` + ``prior_sha256`` (both or neither) bind a SEPARATE
    hash-pinned package as the policy prior while ``checkpoint`` stays the value
    evaluator: the policy-isolation arm of #663 (each scorer on its own trunk;
    production's value, recipe, bury and budgets fixed).  Both packages must
    declare the same encoder version; a mismatch refuses at construction.

    ``bot_factory`` substitutes the constructor for a DIAGNOSTIC subclass so a
    probe does not have to restate the package pinning, the evaluator setup or
    the backend check -- restating them is how a diagnostic ends up measuring
    something subtly different from what serves (#625).  Serving passes None and
    reaches exactly the classes below; whatever a factory returns is checked to
    be the class serving would have built, so it can only ever be a subclass.
    """
    path = str(checkpoint)
    if not path.lower().endswith(".npz"):
        raise PVSearchPolicyError("pv-search serves a NumPy package (.npz); Torch checkpoints are not served")
    actual = file_sha256(path)
    if actual != sha256:
        raise PVSearchPolicyError(f"pv-search package SHA256 mismatch: {actual[:8]} != {sha256[:8]}")
    config = PVSearchConfig(checkpoint_sha256=sha256, worlds=int(worlds), candidates=int(candidates),
                            cap=int(cap), batch_size=int(batch_size),
                            serving_budget_seconds=_serving_budget(serving_budget_seconds),
                            refusal_constraints=refusal_constraints,
                            admission_diversity=admission_diversity,
                            admit_forced_single=admit_forced_single)
    recipe_payload(config)   # refuses a non-bool rule flag before anything loads
    if (prior_checkpoint is None) != (prior_sha256 is None):
        raise PVSearchPolicyError("a separate prior package needs BOTH prior_checkpoint and prior_sha256")
    predict = NumpyPriorPredict(path, sha256)
    if prior_checkpoint is not None:
        prior_path = str(prior_checkpoint)
        if not prior_path.lower().endswith(".npz"):
            raise PVSearchPolicyError("the prior package must be a NumPy package (.npz)")
        prior_actual = file_sha256(prior_path)
        if prior_actual != prior_sha256:
            raise PVSearchPolicyError(f"prior package SHA256 mismatch: {prior_actual[:8]} != {prior_sha256[:8]}")
        prior_predict = NumpyPriorPredict(prior_path, prior_sha256)
        if int(prior_predict.version) != int(predict.version):
            raise PVSearchPolicyError(f"prior package is encoder v{prior_predict.version}, the value "
                                      f"package v{predict.version}; they must agree")
        predict = prior_predict
    evaluator = shared_evaluator(path, threads=threads, max_batch=config.batch_size, encoding=ENCODING)
    if getattr(evaluator, "backend", None) != "numpy":
        raise PVSearchPolicyError("pv-search requires the numpy evaluator backend")
    expected = PVSearchBot if bury_arm is None else PVSearchBuryBot
    build = expected if bot_factory is None else bot_factory
    if bury_arm is None:
        bot = build(predict, evaluator=evaluator, version=predict.version, config=config,
                    checkpoint=path, seed=int(seed))
    else:
        bot = build(predict, evaluator=evaluator, version=predict.version, config=config,
                    checkpoint=path, seed=int(seed), bury_arm=bury_arm,
                    bury_config=bury_config,
                    bury_serving_budget_seconds=bury_serving_budget_seconds)
    if not isinstance(bot, expected):
        raise PVSearchPolicyError(
            f"bot_factory built {type(bot).__name__}, not a {expected.__name__}")
    bot.prior_checkpoint = None if prior_checkpoint is None else str(prior_checkpoint)
    bot.prior_sha256 = prior_sha256
    if name is not None:
        bot.policy_name = name
    return bot


def pv_registry_entries(checkpoint: str, *, sha256: str, worlds: int = DEFAULTS["worlds"],
                        candidates: int = DEFAULTS["candidates"], cap: int = DEFAULTS["cap"],
                        batch_size: int = DEFAULTS["batch_size"], seed: int = DEFAULTS["seed"],
                        serving_budget_seconds=None, bury_arm: str | None = None,
                        bury_config: CWVBuryConfig | None = None,
                        bury_serving_budget_seconds=None, bot_factory=None,
                        prior_checkpoint: str | None = None,
                        prior_sha256: str | None = None,
                        refusal_constraints: bool = SAMPLER_DEFAULTS["refusal_constraints"],
                        admission_diversity: bool = ADMISSION_DEFAULTS["admission_diversity"],
                        admit_forced_single: bool = ADMISSION_DEFAULTS["admit_forced_single"]
                        ) -> dict:
    """``{name: factory}`` for one recipe; the factory takes ``seed=`` from `make_bot`.
    With ``bury_arm`` the name carries the bury identity exactly as the shortlist's
    bury wrapper does: ``<play name>-bury-<arm>-<12 hex of the cwv-bury-recipe-v1 identity>``."""
    from ..ai.cwv_policy import checkpoint_id
    config = PVSearchConfig(checkpoint_sha256=sha256, worlds=int(worlds), candidates=int(candidates),
                            cap=int(cap), batch_size=int(batch_size),
                            serving_budget_seconds=_serving_budget(serving_budget_seconds),
                            refusal_constraints=refusal_constraints,
                            admission_diversity=admission_diversity,
                            admit_forced_single=admit_forced_single)
    recipe_payload(config)   # refuses a non-bool rule flag
    ckpt8 = checkpoint_id(checkpoint)
    if ckpt8 != sha256[:8]:
        raise PVSearchPolicyError(f"pv-search package on disk is {ckpt8}, bound SHA256 says {sha256[:8]}")
    prior8 = None
    if (prior_checkpoint is None) != (prior_sha256 is None):
        raise PVSearchPolicyError("a separate prior package needs BOTH prior_checkpoint and prior_sha256")
    if prior_checkpoint is not None:
        prior8 = checkpoint_id(prior_checkpoint)
        if prior8 != prior_sha256[:8]:
            raise PVSearchPolicyError(f"prior package on disk is {prior8}, bound SHA256 says {prior_sha256[:8]}")
    name = pv_policy_name(ckpt8, config, prior8)
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
        if prior_sha256 is not None:
            bury_identity["prior_sha256"] = prior_sha256
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
                               bury_serving_budget_seconds=bury_serving_budget_seconds,
                               bot_factory=bot_factory, prior_checkpoint=prior_checkpoint,
                               prior_sha256=prior_sha256,
                               refusal_constraints=config.refusal_constraints,
                               admission_diversity=config.admission_diversity,
                               admit_forced_single=config.admit_forced_single),
            name)
        if bury_identity is not None:
            if not isinstance(bot, PVSearchBuryBot):
                raise PVSearchPolicyError(f"policy {name!r} built {type(bot).__name__}, not PVSearchBuryBot")
            bot.bury_recipe_identity = {**bury_identity, "config": dict(bury_identity["config"])}
        return bot
    return {name: factory}


def pv_env_recipe(environ=None) -> dict:
    """``SHENGJI_PV_CKPT`` + ``_SHA256`` (both required: an unpinned package is refused),
    the optional ``_PRIOR_CKPT`` + ``_PRIOR_SHA256`` pair (a separate hash-pinned policy
    prior; the value evaluator stays ``_CKPT``) and the optional ``_WORLDS`` / ``_CANDIDATES``
    / ``_CAP`` / ``_BATCH_SIZE`` / ``_SEED`` / ``_SERVING_BUDGET_SECONDS`` knobs and the
    optional ``_ADMISSION_DIVERSITY`` / ``_ADMIT_FORCED_SINGLE`` / ``_REFUSAL_CONSTRAINTS``
    rule flags (``0`` or ``1`` only; unset or empty is off), as keyword arguments for
    `pv_registry_entries`."""
    env = os.environ if environ is None else environ
    checkpoint = env.get(ENV_PREFIX + "CKPT")
    if not checkpoint:
        raise PVSearchPolicyError("SHENGJI_PV_CKPT is not set")
    sha256 = env.get(ENV_PREFIX + "SHA256")
    if not sha256 or len(sha256) != 64:
        raise PVSearchPolicyError("SHENGJI_PV_SHA256 must be the package's full sha256")
    recipe = dict(checkpoint=checkpoint, sha256=sha256)
    prior_ckpt = env.get(ENV_PREFIX + "PRIOR_CKPT")
    prior_sha = env.get(ENV_PREFIX + "PRIOR_SHA256")
    if bool(prior_ckpt) != bool(prior_sha):
        raise PVSearchPolicyError("SHENGJI_PV_PRIOR_CKPT and SHENGJI_PV_PRIOR_SHA256 go together")
    if prior_ckpt:
        if len(prior_sha) != 64:
            raise PVSearchPolicyError("SHENGJI_PV_PRIOR_SHA256 must be the prior package's full sha256")
        recipe.update(prior_checkpoint=prior_ckpt, prior_sha256=prior_sha)
    for key in ("worlds", "candidates", "cap", "batch_size", "seed"):
        raw = env.get(ENV_PREFIX + key.upper())
        if raw not in (None, ""):
            recipe[key] = int(raw)
    raw = env.get(ENV_PREFIX + "SERVING_BUDGET_SECONDS")
    if raw not in (None, ""):
        recipe["serving_budget_seconds"] = float(raw)
    for suffix, key in RULES.items():
        raw = env.get(ENV_PREFIX + suffix)
        if raw in (None, ""):
            continue
        if raw not in ("0", "1"):
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} must be 0 or 1, not {raw!r}")
        if raw == "1":
            recipe[key] = True
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
