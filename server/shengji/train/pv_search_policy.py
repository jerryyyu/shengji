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
``SHENGJI_PV_BURY_ARM`` also accepts ``value`` (the value head's top-ranked
candidate, no rollouts) and ``mc_all`` (a spelling of ``mc``, which already rolls
out every candidate); ``SHENGJI_PV_BURY_ALTERNATIVES`` widens hybrid's finalists.
Each registers under its own ``-bury-<arm>-<id>`` name; the served name is unchanged.
Nothing in this module deploys anything: registration happens only when
``SHENGJI_PV_CKPT`` is set.

Optional paired lookahead tree ("PUCT v2", #436), OFF BY DEFAULT:
``SHENGJI_PV_TREE_SIMS=<S>`` (with the optional ``_TREE_CONT`` / ``_TREE_EPS`` /
``_TREE_ZMIN`` / ``_TREE_BUDGET_FRACTION``) builds `pv_tree_search`'s subclass of the served bot:
after the unchanged PV pass, the candidates the value head cannot separate get
S lookaheads (the policy finishes the current trick), paired by world, and the PV decision is
overridden only when the paired depth-corrected difference is significant
(definition: `pv_tree_search`; recipe and env: `pv_tree_config`).  Set, it
enters the recipe digest and adds ``-ts<S>`` to the name after the rule tokens;
unset, ``PVSearchConfig.tree`` is None and absent from the payload, so every
existing name and the served classes are unchanged.  No change to bury.

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

Optional event-complete refusal observation (#707 board S8), OFF BY DEFAULT:
``SHENGJI_PV_REFUSAL_EVENT_COMPLETE=1`` makes the bot's `RefusalLedger` read
the public notice after EVERY committed play at its table (`observe_public`,
called by the server's commit paths and by the screen's round driver), not
only inside its own decisions.  ``Round.notice`` is replaced by the next failed
throw and expires after ``NOTICE_PLAYS`` accepted plays, so a ledger that
observes only when its bot decides misses notices -- its own failed throw's
notice above all, which is posted after the decision (#745: 6 of 8 retained on
the partner fixture at the actor's seat).  A notice is set at the commit of the
failed throw and can only be replaced by a LATER commit, so observing once
after every committed play sees every notice.  ``0`` or ``1`` only; on, it
REQUIRES ``SHENGJI_PV_REFUSAL_CONSTRAINTS=1`` (refused at construction
otherwise: with the sampler rule off no decision reads the ledger, and a name
token for a rule with no effect would be a lie), enters the recipe digest and
adds ``-rcec`` to the registry name right after ``-rc``; off, `observe_public`
is a no-op, the ledger is fed exactly as before (inside `_worlds`) and every
existing name, digest, sampled world and decision record is unchanged
(release 38: ``pv-search-491ee4bf-w64-k8-div-rc-tb-la-r7092480e-bury-hybrid-5517ddbd7457``).
The engine and the hashed encoder closure are untouched; nothing is added to
``Round``.

Optional admission width rule (#676 C), OFF BY DEFAULT: ``SHENGJI_PV_ADAPTIVE_K=1``
admits ``candidates_lead_multi`` (16) instead of ``candidates`` (8) when the seat
is leading and the scored legal set holds a multi-card action -- the K=8 ballot
plus the next-best eight by the same policy preference, decided before the
diversity caps and the forced extras (definition and the evidence:
`policy_value_search`).  ``0`` or ``1`` only; on, it enters the recipe digest
with its width and adds ``-ak16`` (the width) to the name as the last token; off,
it is absent from the payload and K is 8 everywhere.

Optional selection rule (#676 E, #677 strategy 2), OFF BY DEFAULT:
``SHENGJI_PV_TIEBREAK_POINTS=1`` lets the final choice among candidates whose
value means lie within ``tiebreak_epsilon`` (0.02 of a signed level, the head's
own units) of the best go to the one that banks the most root-team points when
the current trick resolves under the search's own trick finisher, summed over
the sampled worlds (definition: `policy_value_search`).  ``0`` or ``1`` only; on,
it enters the recipe digest with its epsilon and adds ``-tb`` to the name after
the admission tokens; off, it is absent from the payload, so every existing name
and the served selection (the plain argmax) are unchanged.  The rebuild runs
under the play budget; on expiry the tie-break abandons itself and the argmax is
played (the value pass was complete), never the anchor fallback.

Optional anchor rule (#676 online lead review, board A7), OFF BY DEFAULT:
``SHENGJI_PV_LEAD_ANCHOR=1`` replaces the heuristic anchor in slot 0 when the
seat is leading and that anchor is a single non-trump card that is not the top
live card of its suit: by the highest plain pair/tractor in the scored set,
else the policy's top-ranked action, else the heuristic card stays; the
replaced card still competes for the policy slots (definition and evidence:
`policy_value_search`).  ``0`` or ``1`` only; on, it enters the recipe digest
and adds ``-la`` to the name as the last rule token; off, it is absent from the
payload, so every existing name (production:
``pv-search-491ee4bf-w64-k8-r4a09aef5-bury-hybrid-355958b4db25``) and slot 0
are unchanged.  No model call is added.

Optional lead selection rule (#676 online lead review, board A8), OFF BY DEFAULT:
``SHENGJI_PV_LEAD_TIEBREAK_PRIOR=1`` -- only when the seat is LEADING, among the
admitted candidates whose value mean is within ``lead_tiebreak_epsilon`` (0.02
of a signed level, the same scale and constant as ``tiebreak_epsilon``) of the
best, the one with the highest policy prior score (the admission's ranking
score) is played; an exact prior tie keeps the argmax.  With
``SHENGJI_PV_TIEBREAK_POINTS=1`` as well the rule is additive: the points rule
runs first, unchanged, any selection it moves is kept, and the prior decides
only on a lead where the points rule leaves the argmax in place (definition:
`policy_value_search`).  ``0`` or ``1`` only; on, it enters the
recipe digest with its epsilon and adds ``-lp`` to the name as the last rule
token; off, it is absent from the payload, so every existing name and the
served selection are unchanged.  No model call and no leaf rebuild is added.
The prior rule itself costs nothing, so it needs no budget check; the points
rule keeps its own deadline handling.

Optional played-action rule (OXPS round 1, release 38), OFF BY DEFAULT:
``SHENGJI_PV_DOOMED_THROW_SWAP=1`` -- on a LEAD whose selected action is a throw
the engine refuses in EVERY sampled world with the same forced component, that
component is played instead of the throw (the throw's leaf already is that
component played, so the value is unchanged; only the public failed-throw notice
and the cards it shows go away; definition: `policy_value_search`).  ``0`` or
``1`` only; on, it enters the recipe digest and adds ``-dts`` to the name as the
last rule token; off, it is absent from the payload, so every existing name
(release 38: ``pv-search-491ee4bf-w64-k8-div-rc-tb-la-r7092480e-bury-hybrid-5517ddbd7457``)
and the played action are unchanged.  No model call and no leaf rebuild is
added; the W engine validations run under the play budget and, on expiry, the
check abandons itself and the selected action is played.

Optional admission exclusion (#676 online lead review fix 3, board #707 S4, was
A9), OFF BY DEFAULT: ``SHENGJI_PV_SMALL_JOKER_GUARD=1`` -- on a LEAD where the
seat holds a small joker and at least three other trumps while a big joker is
still outstanding (not in its hand, not played, not in its own kitty: public
information and its own holdings only), the single small-joker lead is dropped
from the admission, slot 0 included (definition and evidence:
`policy_value_search`).  ``0`` or ``1`` only; on, it enters the recipe digest and
adds ``-sjg`` to the name as the last rule token; off, it is absent from the
payload, so every existing name (release 38:
``pv-search-491ee4bf-w64-k8-div-rc-tb-la-r7092480e-bury-hybrid-5517ddbd7457``)
and the admitted ballot are unchanged.  No model call and no leaf rebuild is
added.

Optional unresolved-decision evidence rule, OFF BY DEFAULT:
``SHENGJI_PV_ADAPTIVE_WORLDS=1`` -- when the top-2 admitted candidates' value
gap on the W base worlds is below ``ADAPTIVE_WORLDS_Z`` (2) paired standard
errors, the admitted candidates are scored on ``ADAPTIVE_WORLDS_EXTRA_ROUNDS``
(3) more batches of W sampled worlds and selected on the 4W means; under a
serving budget the extra stage starts only below 50% of it, after the base
decision is finalized, and abandons itself at 80% or on the hard budget or any
error, playing the cached base decision (definition and evidence: `PVSearchBot`).
``0`` or ``1`` only; on, it enters the recipe digest with its constants and adds
``-aw`` to the name as the last rule token; it refuses the tree.  Off, it is
absent from the payload, so every existing name (release 42:
``pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-r0f40c8b5-bury-hybrid-273fed4cd40d``)
and every decision are unchanged.

Its leads-only scope, OFF BY DEFAULT: ``SHENGJI_PV_ADAPTIVE_WORLDS_LEADS=1`` --
exactly the same rule (the same constants, the same `_adaptive_worlds_decision`),
run only when the acting seat LEADS (`policy_value_search.leading`); on a follow
the decision takes the flag-off path, byte for byte (no matrix, no extra draw,
no record key).  ``0`` or ``1`` only; exclusive with ``SHENGJI_PV_ADAPTIVE_WORLDS``
(both on refuses); on, it enters the recipe digest with the same constants and
adds ``-awl`` to the name as the last rule token; it refuses the tree.  Off,
every existing name (release 42 above; the ``aw`` name
``pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-aw-reba5b0fc-bury-hybrid-0fc096017bf0``)
and every decision are unchanged.

Optional lead admission width rule, OFF BY DEFAULT:
``SHENGJI_PV_WIDE_LEAD_ADMISSION=1`` -- when the acting seat LEADS
(`policy_value_search.leading`) the policy admission shortlist is
``WIDE_LEAD_K`` (32) wide instead of ``candidates`` (8), through the same
admission path (anchor slot 0, ``lead_anchor``, the diversity caps, the forced
extras, the small-joker guard -- all as served, only K is larger); on a follow
the decision is the flag-off one, byte for byte (definition and evidence:
`PVSearchBot`).  ``0`` or ``1`` only; it refuses ``SHENGJI_PV_ADAPTIVE_K`` (two
lead-width rules); on, it enters the recipe digest with ``WIDE_LEAD_K`` and adds
``-wla`` to the name in the width slot, right after ``-ak16`` (the two are
exclusive, so they never both appear) and before ``-la``.  Off, every existing
name (release 42, ``aw``, ``awl`` above) and every decision are unchanged.

Optional selection rule replacing the played-action swap (YJQJ round 1, release
42), OFF BY DEFAULT: ``SHENGJI_PV_DOOMED_THROW_RESELECT=1`` -- when the selected
lead is a throw the swap would replace (refused in EVERY sampled world with one
forced component), neither the throw nor its forced component is played: both
are excluded and the bot's own selection rules re-select among the remaining
admitted candidates (definition, record and budget semantics:
`policy_value_search`).  ``0`` or ``1`` only; EXCLUSIVE with
``SHENGJI_PV_DOOMED_THROW_SWAP`` (both on refuses) and refused with the tree; on,
it enters the recipe digest and adds ``-dtr`` to the name as the last rule
token.  Off, it is absent from the payload, so every existing name (release 42
above; the ``aw`` name above; the ``awl`` name
``pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-awl-r7965ea65-bury-hybrid-ed3b15d1e9a0``)
and every decision are unchanged.  No model call and no leaf rebuild beyond the
selection rules' own is added.
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
from .policy_value_search import (ADAPTIVE_K_DEFAULTS, ADMISSION_DEFAULTS, FORCED_EXTRA_SLOTS,
                                  DOOMED_THROW_DEFAULTS, DOOMED_THROW_RESELECT_DEFAULTS,
                                  LEAD_ANCHOR_DEFAULTS,
                                  LEAD_TIEBREAK_DEFAULTS, SMALL_JOKER_GUARD_DEFAULTS,
                                  TIEBREAK_DEFAULTS, PolicyValueBot, leading)
from .optional_stage import OptionalStage
from .cwv_bury_policy import (_ARMS as BURY_ARMS, ARM_ALIASES as BURY_ARM_ALIASES,
                              BuryPolicyError, CWVBuryConfig,
                              CWVBuryMixin, _serving_budget as _bury_budget)
from .pv_tree_config import PVTreeConfig, tree_env, tree_token

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
#: the optional sampler rule (`ai.refusal`) and its event-complete observation
#: (#707 S8; requires the sampler rule): env flag -> recipe key, and the defaults
SAMPLER_RULES = {"REFUSAL_CONSTRAINTS": "refusal_constraints",
                 "REFUSAL_EVENT_COMPLETE": "refusal_event_complete"}
SAMPLER_DEFAULTS = dict(refusal_constraints=False, refusal_event_complete=False)
#: name tokens, in name order, for the rules that are on
SAMPLER_TOKENS = (("refusal_constraints", "rc"), ("refusal_event_complete", "rcec"))
#: the optional selection rule (`policy_value_search`): env flag -> recipe key
TIEBREAK_RULE = {"TIEBREAK_POINTS": "tiebreak_points"}
#: the optional admission width rule (`policy_value_search`): env flag -> recipe key
ADAPTIVE_K_RULE = {"ADAPTIVE_K": "adaptive_k"}
#: its name token encodes the width it admits on a multi-card lead
ADAPTIVE_K_TOKEN = ("adaptive_k", f"ak{ADAPTIVE_K_DEFAULTS['candidates_lead_multi']}")
#: the optional anchor rule (`policy_value_search`): env flag -> recipe key
LEAD_ANCHOR_RULE = {"LEAD_ANCHOR": "lead_anchor"}
#: the optional lead selection rule (`policy_value_search`): env flag -> recipe key
LEAD_TIEBREAK_RULE = {"LEAD_TIEBREAK_PRIOR": "lead_tiebreak_prior"}
#: the optional played-action rule (`policy_value_search`): env flag -> recipe key
DOOMED_THROW_RULE = {"DOOMED_THROW_SWAP": "doomed_throw_swap"}
#: the optional selection rule replacing it (`policy_value_search`; exclusive with it)
DOOMED_THROW_RESELECT_RULE = {"DOOMED_THROW_RESELECT": "doomed_throw_reselect"}
#: the optional single small-joker lead exclusion (`policy_value_search`, #707 S4)
SMALL_JOKER_GUARD_RULE = {"SMALL_JOKER_GUARD": "small_joker_guard"}
#: the optional unresolved-decision evidence rule (`PVSearchBot._adaptive_worlds_means`)
#: and its leads-only scope (the same rule, run only on a lead; exclusive with it)
ADAPTIVE_WORLDS_RULE = {"ADAPTIVE_WORLDS": "adaptive_worlds",
                        "ADAPTIVE_WORLDS_LEADS": "adaptive_worlds_leads"}
ADAPTIVE_WORLDS_DEFAULTS = dict(adaptive_worlds=False, adaptive_worlds_leads=False)
#: the optional lead admission width rule (`PVSearchBot._admission_k`)
WIDE_LEAD_RULE = {"WIDE_LEAD_ADMISSION": "wide_lead_admission"}
WIDE_LEAD_DEFAULTS = dict(wide_lead_admission=False)
#: `wide_lead_admission`: the policy admission width on every lead (served K is 8)
WIDE_LEAD_K = 32
#: `adaptive_worlds`: the top-2 value gap is unresolved when it is below this many
#: paired standard errors of (v_a - v_b) over the base worlds
ADAPTIVE_WORLDS_Z = 2.0
#: `adaptive_worlds`: on an unresolved decision, this many further batches of W
#: worlds are drawn and the admitted candidates scored on them (4W in all)
ADAPTIVE_WORLDS_EXTRA_ROUNDS = 3
#: `adaptive_worlds` under a serving budget: the extra stage starts only while
#: the decision has used less than this share of the budget ...
ADAPTIVE_WORLDS_START_FRACTION = 0.5
#: ... and abandons itself (base means and worlds kept) at this share
ADAPTIVE_WORLDS_SOFT_FRACTION = 0.8
#: `adaptive_worlds`: the per-decision rule records the base finalization sets
#: and an abandoned re-selection could overwrite; snapshotted and restored
ADAPTIVE_WORLDS_RULE_STATE = ("_tiebreak", "_lead_tiebreak", "_doomed_throw", "_last_sampling")
#: every optional 0/1 rule flag, env suffix -> recipe key, and every name token in
#: name order (admission rules, the sampler rules, selection, width -- the
#: multi-card-lead width and the exclusive all-leads width --, anchor, lead
#: selection, played action, small-joker guard, adaptive worlds, its leads-only
#: scope, the doomed-throw re-select): div, fs, rc, rcec, tb, ak16, wla, la, lp,
#: dts, sjg, aw, awl, dtr
RULE_FLAGS = {**ADMISSION_RULES, **SAMPLER_RULES, **TIEBREAK_RULE, **ADAPTIVE_K_RULE,
              **LEAD_ANCHOR_RULE, **LEAD_TIEBREAK_RULE, **DOOMED_THROW_RULE,
              **SMALL_JOKER_GUARD_RULE, **ADAPTIVE_WORLDS_RULE, **WIDE_LEAD_RULE,
              **DOOMED_THROW_RESELECT_RULE}
RULES = RULE_FLAGS
RULE_TOKENS = ADMISSION_TOKENS + SAMPLER_TOKENS + (("tiebreak_points", "tb"), ADAPTIVE_K_TOKEN,
                                                   ("wide_lead_admission", "wla"),
                                                   ("lead_anchor", "la"),
                                                   ("lead_tiebreak_prior", "lp"),
                                                   ("doomed_throw_swap", "dts"),
                                                   ("small_joker_guard", "sjg"),
                                                   ("adaptive_worlds", "aw"),
                                                   ("adaptive_worlds_leads", "awl"),
                                                   ("doomed_throw_reselect", "dtr"))
ENV_PREFIX = "SHENGJI_PV_"
_WIDE_LEAD_EXCLUSIVE = ("wide_lead_admission and adaptive_k are exclusive "
                        "(SHENGJI_PV_WIDE_LEAD_ADMISSION=1 with SHENGJI_PV_ADAPTIVE_K=1)")
_ADAPTIVE_WORLDS_EXCLUSIVE = ("adaptive_worlds and adaptive_worlds_leads are exclusive "
                              "(SHENGJI_PV_ADAPTIVE_WORLDS=1 with SHENGJI_PV_ADAPTIVE_WORLDS_LEADS=1)")
_DOOMED_THROW_EXCLUSIVE = ("doomed_throw_swap and doomed_throw_reselect are exclusive "
                           "(SHENGJI_PV_DOOMED_THROW_SWAP=1 with SHENGJI_PV_DOOMED_THROW_RESELECT=1)")
#: the fallback record's ``error_message`` is the exception text cut to this
#: many characters (#707 S9)
ERROR_MESSAGE_MAX = 200
#: the sampler's cumulative counters whose per-decision change the record
#: carries as ``<name>_delta`` (#707 S9; read, never written)
SAMPLER_DELTA_COUNTERS = ("impossible_worlds", "rejected_worlds")


class PVSearchPolicyError(RuntimeError):
    """The production wrapper refused to build or to run a decision.

    ``stage`` (#707 S9, telemetry only) is a short stable name for the
    decision-time raise site, copied into the fallback record as
    ``error_stage``; ``None`` where a raise site names none."""

    stage = None

    def __init__(self, *args, stage=None):
        super().__init__(*args)
        if stage is not None:
            self.stage = stage


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
    # the optional paired lookahead tree (`pv_tree_search`, #436); None = off and
    # ABSENT from the recipe payload, so every pre-existing name is unchanged
    tree: PVTreeConfig | None = None
    # the optional admission rules (#676 A/C) and the sampler rule (#676 B); OFF by
    # default and, while off, ABSENT from the recipe payload so every pre-existing
    # name is unchanged
    admission_diversity: bool = ADMISSION_DEFAULTS["admission_diversity"]
    admit_forced_single: bool = ADMISSION_DEFAULTS["admit_forced_single"]
    refusal_constraints: bool = SAMPLER_DEFAULTS["refusal_constraints"]
    # the event-complete observation of the sampler rule (#707 S8): the same
    # contract, and on only together with ``refusal_constraints``
    refusal_event_complete: bool = SAMPLER_DEFAULTS["refusal_event_complete"]
    # the optional selection rule (#676 E); the same contract
    tiebreak_points: bool = TIEBREAK_DEFAULTS["tiebreak_points"]
    # the optional admission width rule (#676 C); the same contract
    adaptive_k: bool = ADAPTIVE_K_DEFAULTS["adaptive_k"]
    # the optional anchor rule (#676 online lead review); the same contract
    lead_anchor: bool = LEAD_ANCHOR_DEFAULTS["lead_anchor"]
    # the optional lead selection rule (board A8); the same contract
    lead_tiebreak_prior: bool = LEAD_TIEBREAK_DEFAULTS["lead_tiebreak_prior"]
    # the optional played-action rule (OXPS r1 doomed throw); the same contract
    doomed_throw_swap: bool = DOOMED_THROW_DEFAULTS["doomed_throw_swap"]
    # the optional single small-joker lead exclusion (#707 S4); the same contract
    small_joker_guard: bool = SMALL_JOKER_GUARD_DEFAULTS["small_joker_guard"]
    # the optional unresolved-decision evidence rule; the same contract
    adaptive_worlds: bool = ADAPTIVE_WORLDS_DEFAULTS["adaptive_worlds"]
    # its leads-only scope (exclusive with ``adaptive_worlds``); the same contract
    adaptive_worlds_leads: bool = ADAPTIVE_WORLDS_DEFAULTS["adaptive_worlds_leads"]
    # the optional lead admission width (exclusive with ``adaptive_k``); the same contract
    wide_lead_admission: bool = WIDE_LEAD_DEFAULTS["wide_lead_admission"]
    # the optional selection rule replacing the swap (exclusive with it); the same contract
    doomed_throw_reselect: bool = DOOMED_THROW_RESELECT_DEFAULTS["doomed_throw_reselect"]


def recipe_payload(config: PVSearchConfig) -> dict:
    """The digested recipe: every field, except that an optional rule that is
    OFF is omitted (the payload of the pre-rule recipe, byte for byte) and a
    rule that is on carries its parameters."""
    payload = asdict(config)
    if config.tree is None:
        del payload["tree"]
    elif not isinstance(config.tree, PVTreeConfig):
        raise PVSearchPolicyError("tree must be a PVTreeConfig or None")
    for key in RULE_FLAGS.values():
        if type(payload[key]) is not bool:
            raise PVSearchPolicyError(f"{key} must be a bool")
        if not payload[key]:
            del payload[key]
    if config.refusal_event_complete and not config.refusal_constraints:
        raise PVSearchPolicyError("refusal_event_complete requires refusal_constraints "
                                  "(SHENGJI_PV_REFUSAL_EVENT_COMPLETE=1 needs "
                                  "SHENGJI_PV_REFUSAL_CONSTRAINTS=1)")
    if config.admission_diversity:
        payload["max_per_structure"] = ADMISSION_DEFAULTS["max_per_structure"]
    if config.admit_forced_single:
        payload["forced_min_fraction"] = ADMISSION_DEFAULTS["forced_min_fraction"]
    if config.tiebreak_points:
        payload["tiebreak_epsilon"] = TIEBREAK_DEFAULTS["tiebreak_epsilon"]
    if config.adaptive_k:
        payload["candidates_lead_multi"] = ADAPTIVE_K_DEFAULTS["candidates_lead_multi"]
    if config.wide_lead_admission:
        if config.adaptive_k:
            raise PVSearchPolicyError(_WIDE_LEAD_EXCLUSIVE)
        payload["wide_lead_k"] = WIDE_LEAD_K
    if config.lead_tiebreak_prior:
        payload["lead_tiebreak_epsilon"] = LEAD_TIEBREAK_DEFAULTS["lead_tiebreak_epsilon"]
    if config.doomed_throw_swap and config.doomed_throw_reselect:
        raise PVSearchPolicyError(_DOOMED_THROW_EXCLUSIVE)
    if config.doomed_throw_reselect and config.tree is not None:
        # the tree re-selects on its own Q matrix after `_select`
        raise PVSearchPolicyError("doomed_throw_reselect does not combine with the tree "
                                  "(SHENGJI_PV_DOOMED_THROW_RESELECT=1 with SHENGJI_PV_TREE_SIMS)")
    if config.adaptive_worlds and config.adaptive_worlds_leads:
        raise PVSearchPolicyError(_ADAPTIVE_WORLDS_EXCLUSIVE)
    if config.adaptive_worlds or config.adaptive_worlds_leads:
        if config.tree is not None:
            # the tree reads the PV pass's W x K matrix and re-selects on it; a
            # 4W selection would mix two evidence bases (PVSearchBot docstring)
            flag = "ADAPTIVE_WORLDS" if config.adaptive_worlds else "ADAPTIVE_WORLDS_LEADS"
            key = RULE_FLAGS[flag]
            raise PVSearchPolicyError(f"{key} does not combine with the tree "
                                      f"(SHENGJI_PV_{flag}=1 with SHENGJI_PV_TREE_SIMS)")
        payload.update(adaptive_worlds_z=ADAPTIVE_WORLDS_Z,
                       adaptive_worlds_extra_rounds=ADAPTIVE_WORLDS_EXTRA_ROUNDS,
                       adaptive_worlds_start_fraction=ADAPTIVE_WORLDS_START_FRACTION,
                       adaptive_worlds_soft_fraction=ADAPTIVE_WORLDS_SOFT_FRACTION)
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
    rules += tree_token(config.tree)   # "" while the tree is off
    return (f"pv-search-{ckpt8}{prior}-w{config.worlds}-k{config.candidates}{rules}"
            f"-r{recipe_digest(config)}")


class _AdaptiveWorldsExpired(Exception):
    """The `adaptive_worlds` extra stage reached its soft deadline, or a rule in
    its re-selection absorbed an expiry (internal)."""


class PVSearchBot(PolicyValueBot):
    """`PolicyValueBot` on a NumPy package, with the serving budget and record.

    Optional unresolved-decision evidence rule ``adaptive_worlds`` (OFF BY
    DEFAULT; while off `_search` takes exactly the path it always took, no
    matrix is allocated, no extra world is drawn, and the record gains no key).
    Evidence: on release 42 (smv3out-491ee4bf, W64, K8) the value head decides
    about 90% of picks, and on LEADS the top-2 value gap was within one paired
    standard error in 35% of decisions (two SE in 56%); resampling the 64 worlds
    flipped the pick 18% of the time.  With the rule on, after the admitted
    candidates are scored on the W base worlds (serving's `_score_leaves`, with
    its additive ``capture`` keeping the W x K matrix) and when at least two
    are admitted: ``a`` is the value-mean argmax, ``b`` the runner-up (highest
    other mean, lowest admitted position on a tie), ``margin = m_a - m_b`` and
    ``se`` the paired standard error of ``v_a - v_b`` over the base worlds
    (sample std, ddof 1, over sqrt W; W < 2 never triggers).  The decision is
    unresolved when ``margin < ADAPTIVE_WORLDS_Z * se`` (2.0), or when both are
    exactly zero.  Then ``ADAPTIVE_WORLDS_EXTRA_ROUNDS`` (3) further batches of
    W worlds are drawn through this bot's own `_worlds` (the same sampler, the
    refusal-aware path, the void check), ONLY the admitted candidates are scored
    on them (`_score_leaves`), and the means are ``(base sums + extra sums) /
    4W``.  Admission is unchanged (base worlds only); `_select` and
    `_swap_doomed_throw` receive the combined world list, so every later rule
    sees the same evidence the means came from.
    Budget: the extra stage must never cost the decision its search result
    (#936 HOLD).  The base decision is FINALIZED first, exactly as the flag-off
    path finalizes it (`_select` and `_swap_doomed_throw` on the base worlds
    after the pre-success hard check), and cached with a snapshot of the rule
    records it set.  With a serving budget the extra stage starts only while
    elapsed < ``START_FRACTION`` (50%) of the budget, and every check inside it
    (sampling, scoring, the 4W `_select` and `_swap_doomed_throw`) tests the
    hard budget, then a soft deadline at ``SOFT_FRACTION`` (80%); a final hard
    check precedes publishing the 4W decision.  Any expiry or error there --
    including a hard expiry a rule absorbed -- abandons the stage: the
    snapshot is restored and the cached base decision is played (the shared
    transaction `optional_stage.OptionalStage`),
    ``work_complete`` True, never the heuristic fallback
    (`_adaptive_worlds_decision`).  A failure in the base pass or base
    finalization is a base failure and falls back exactly as flag-off.
    Record (only with the rule on): ``adaptive_worlds_triggered`` (the decision
    was unresolved), ``_total`` (worlds behind the selection), ``_margin``,
    ``_se``, ``_skipped_budget`` (unresolved but past the start share),
    ``_abandoned`` (+ ``_abandon_reason`` ``soft_budget``/``hard_budget``/
    ``error``, ``_abandon_error`` the exception class, ``_abandoned_evaluations``
    the leaves of COMPLETED extra rounds thrown away; a round cut by a check
    is not counted), ``_changed`` (the selection's value
    argmax differs from the base argmax), ``_played_changed`` (the cards differ
    from the base decision's), ``_sampler_advanced`` (extra draws were begun:
    the sampler stream moved, even when abandoned -- later decisions' worlds
    differ, never this one's result) and ``_base_seconds`` (elapsed at the base
    finalization; ``seconds`` stays the total).  ``value_means``,
    ``value_batches`` and ``value_evaluations`` describe the published
    selection: the 4W pass when it completed, else exactly the base pass;
    ``worlds`` stays the base W.
    Leads-only scope ``adaptive_worlds_leads`` (exclusive with the rule): the
    same `_adaptive_worlds_decision`, entered only when `leading(rnd)`; on a
    follow `_search` takes the flag-off path and the record carries no
    ``adaptive_worlds_*`` key, so a follow's decision, record and sampler
    stream are the flag-off ones (the record's key set says whether the rule
    ran: present on every lead, absent on every follow).

    Optional lead admission width ``wide_lead_admission`` (OFF BY DEFAULT;
    while off `_admission_k` is the harness's and nothing else differs).  On a
    LEAD (`leading`: no play yet in the trick) the admission width is
    ``max(candidates, WIDE_LEAD_K)`` (32 against the served 8), decided in
    `_admission_k`, i.e. inside the harness's own `_admit`: slot 0 (the
    heuristic anchor, ``lead_anchor``'s replacement, the small-joker guard's),
    the ``admission_diversity`` caps and back-fill and the ``admit_forced_single``
    extras all run exactly as served, only with the wider K, so the ballot is
    what a ``candidates=32`` recipe admits on that lead.  On a FOLLOW the width
    is ``candidates`` and the decision, the record (no ``wide_lead_*`` key) and
    the sampler stream are the flag-off ones.  The candidate-budget check in
    `_search` allows ``k_used`` up to ``WIDE_LEAD_K`` on a lead (plus the
    ``FORCED_EXTRA_SLOTS``), and the existing bound elsewhere.  Refuses
    ``adaptive_k`` (two width rules on the same leads would need a precedence
    nobody has measured).  Combines with ``adaptive_worlds`` /
    ``adaptive_worlds_leads``: their extra stage re-scores the admitted set,
    which on a lead is the wider one (4W x up to 34 leaves), under the same
    50%/80% budget guards.  Record (leads only, flag on):
    ``wide_lead_admission_k`` (the width used, before forced extras) and
    ``wide_lead_admission_applied`` (it exceeded ``candidates``).
    Evidence (DEV diagnostics on release 42, archives
    ``~/shengji-archive/2026-09-13/readouts/leaddiag-r42-20261008`` and
    ``leaddiag2-r42-20261008``): the value head's best lead lies outside the
    8-move policy shortlist at 44% of leads (51% of multi-card leads); a K=32
    policy shortlist through this admission path cuts lead regret against the
    value head's own 512-world reference from 0.0223 to 0.0084 (87% of the
    full-set gain) at about 3.1x the lead cost (p99 0.46 s single core on
    cloud).  Earlier served evidence: adaptive K16 on multi-card leads (v41ak
    vs release 36) -0.006, inconclusive.  This is agreement with the value
    head, not playing strength.
    Only this class: the harness `PolicyValueBot.decide_play` has no budget and
    no capture path.  A subclass that replaces `_value_means` (the tree, which
    re-selects on the PV pass's W x K matrix; the belief-weighted exploiter) is
    refused with the rule on: its reducer and this rule's would disagree about
    what the means are.
    """

    # class-level OFF default (as `small_joker_guard`): a bare instance built
    # without __init__ takes the served path
    adaptive_worlds = ADAPTIVE_WORLDS_DEFAULTS["adaptive_worlds"]
    adaptive_worlds_leads = ADAPTIVE_WORLDS_DEFAULTS["adaptive_worlds_leads"]
    _adaptive_worlds = None
    wide_lead_admission = WIDE_LEAD_DEFAULTS["wide_lead_admission"]
    _wide_lead = None

    def __init__(self, predict, *, evaluator, version: int, config: PVSearchConfig,
                 checkpoint: str, seed: int = 0):
        super().__init__(predict, evaluator=evaluator, candidates=config.candidates,
                         batch_size=config.batch_size, worlds=config.worlds,
                         cap=config.cap, seed=seed,
                         admission_diversity=config.admission_diversity,
                         admit_forced_single=config.admit_forced_single,
                         tiebreak_points=config.tiebreak_points,
                         adaptive_k=config.adaptive_k,
                         lead_anchor=config.lead_anchor,
                         lead_tiebreak_prior=config.lead_tiebreak_prior,
                         doomed_throw_swap=config.doomed_throw_swap,
                         small_joker_guard=config.small_joker_guard,
                         doomed_throw_reselect=config.doomed_throw_reselect)
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
        # #707 S8: the ledger also reads the notice after every committed play
        # at the table (`observe_public`), never only at this bot's decisions
        self.refusal_event_complete = bool(config.refusal_event_complete)
        if self.refusal_event_complete and not self.refusal_constraints:
            raise PVSearchPolicyError("refusal_event_complete requires refusal_constraints")
        self._refusals = RefusalLedger()
        self._last_sampling = {}
        for key in ("adaptive_worlds", "adaptive_worlds_leads"):
            if type(getattr(config, key)) is not bool:
                raise PVSearchPolicyError(f"{key} must be a bool")
            if getattr(config, key) and type(self)._value_means is not PVSearchBot._value_means:
                raise PVSearchPolicyError(f"{key} needs serving's own _value_means; "
                                          f"{type(self).__name__} replaces it")
        if config.adaptive_worlds and config.adaptive_worlds_leads:
            raise PVSearchPolicyError(_ADAPTIVE_WORLDS_EXCLUSIVE)
        self.adaptive_worlds = config.adaptive_worlds
        self.adaptive_worlds_leads = config.adaptive_worlds_leads
        self._adaptive_worlds = None
        if type(config.wide_lead_admission) is not bool:
            raise PVSearchPolicyError("wide_lead_admission must be a bool")
        if config.wide_lead_admission and config.adaptive_k:
            raise PVSearchPolicyError(_WIDE_LEAD_EXCLUSIVE)
        self.wide_lead_admission = config.wide_lead_admission
        self._wide_lead = None
        if config.doomed_throw_reselect and config.tree is not None:
            raise PVSearchPolicyError("doomed_throw_reselect does not combine with the tree")
        # The screen's duel reads the production search-time counter off every side
        # (`oracle.screen.play_screen_round`: ``arm_search_secs``); accumulated wall
        # seconds of `decide_play`, as `MCBot.search_secs`.
        self.search_secs = 0.0

    # -- the public-event hook (#707 S8) ---------------------------------------

    def observe_public(self, rnd) -> None:
        """Read the round's public failed-throw notice into this bot's ledger.

        Called by the table's round driver after EVERY committed play (the
        server's commit paths on the committed room bot, `ai.env` on every
        seat's bot), so the ledger sees each notice before the next failed
        throw replaces it -- its own failed throw's notice included, which is
        posted only after `decide_play` returned.  A no-op unless BOTH
        ``refusal_constraints`` and ``refusal_event_complete`` are on, so a
        flag-off bot's ledger is fed exactly as before (inside `_worlds`).
        `RefusalLedger.observe` is idempotent for a notice already held, so the
        decision-time read and this one never double-count.  Reads the round;
        never plays, samples or advances the RNG.
        """
        if self.refusal_constraints and self.refusal_event_complete:
            self._refusals.observe(rnd)

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
            raise PVSearchPolicyError(f"policy world sampling short: {len(worlds)}/{self.worlds}",
                                      stage="world_sampling_short")
        if any(rnd.ordering.eff_suit(c) in mem.voids[s]
               for hands, _ in worlds for s in range(4) if s != seat for c in hands[s]):
            raise PVSearchPolicyError("policy world sampling violates public voids",
                                      stage="world_sampling_void_check")
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
            raise PVSearchPolicyError("value matrix has unfilled cells", stage="value_matrix_unfilled")
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

    # -- the optional lead admission width (class docstring) ----------------------

    def _admission_k(self, rnd, actions, preferences):
        """The harness's width, or under ``wide_lead_admission`` on a lead
        ``max(candidates, WIDE_LEAD_K)``; sets ``self._wide_lead`` (the record
        fields) on that lead.  Called by the harness's `_admit`, so the width
        reaches the same anchor, diversity and forced-extra code as served."""
        if not self.wide_lead_admission or not leading(rnd):
            return super()._admission_k(rnd, actions, preferences)
        k = max(self.candidates, WIDE_LEAD_K)
        self._wide_lead = {"wide_lead_admission_k": int(k),
                           "wide_lead_admission_applied": k > self.candidates}
        return k, k > self.candidates

    def _admission(self, rnd, seat, actions, preferences, anchor_index, worlds,
                   check_budget=None):
        self._wide_lead = None
        return super()._admission(rnd, seat, actions, preferences, anchor_index, worlds,
                                  check_budget)

    def _admission_record(self):
        record = super()._admission_record()
        if self.wide_lead_admission and self._wide_lead is not None:
            record.update(self._wide_lead)
        return record

    def _candidate_limit(self, rnd):
        """The largest admission width (``k_used``) the candidate-budget check
        accepts: the harness's bound, and ``WIDE_LEAD_K`` on a wide lead."""
        limit = max(self.candidates, self.candidates_lead_multi)
        if self.wide_lead_admission and leading(rnd):
            limit = max(limit, WIDE_LEAD_K)
        return limit

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
        # slot 0 is the heuristic anchor, or (``lead_anchor``) its replacement
        # decided inside the admission
        slot0 = self._effective_anchor_key(anchor_key)
        if not chosen or not 0 <= chosen[0] < len(actions) \
                or tuple(sorted(actions[chosen[0]])) != slot0 or len(set(chosen)) != len(chosen) \
                or any(not 0 <= i < len(actions) for i in chosen):
            raise PVSearchPolicyError("admission must return distinct indices into the scored set, anchor first",
                                      stage="admission_contract")
        # The candidate budget bounds what PRODUCTION admits (k_used plus the
        # forced extras).  The harvest mixin appends its exploration draw AFTER the
        # production ballot (keyed in ``_draw_keys``); on the data path there is
        # no serving budget and so no fallback, so counting the draw here raised
        # on a full ballot (#680 at f78ecbe1, found stacking #687).  Draws are
        # excluded from the count; everything else -- a hook override's extras
        # included -- is bounded.
        draw_keys = getattr(self, "_draw_keys", None) or ()
        budgeted = [i for i in chosen if tuple(sorted(actions[i])) not in draw_keys]
        if len(budgeted) > self._adaptive["k_used"] + FORCED_EXTRA_SLOTS \
                or self._adaptive["k_used"] > self._candidate_limit(rnd):
            raise PVSearchPolicyError("admission exceeded the candidate budget",
                                      stage="admission_budget")
        admitted = [actions[i] for i in chosen]
        if self.adaptive_worlds_leads:
            # the leads-only scope: no rule state survives from an earlier lead
            self._adaptive_worlds = None
        if self.adaptive_worlds or (self.adaptive_worlds_leads and leading(rnd)):
            # the optional evidence rule (class docstring): the FINALIZED base
            # decision first, then -- only if it is unresolved and in time -- the
            # 4W re-selection, which on any failure returns the base decision
            means, batches, winner, played, evaluations = self._adaptive_worlds_decision(
                rnd, seat, admitted, worlds, started, check_budget,
                [float(preferences[i]) for i in chosen])
        else:
            means, batches = self._value_means(rnd, seat, admitted, worlds, check_budget)
            evaluations = len(worlds) * len(admitted)
            if check_budget is not None:
                check_budget()   # pre-success: nothing past the deadline is published
            # the optional tie-break rebuilds leaves under the same deadline and, on
            # expiry, abandons itself in favour of the argmax (`policy_value_search`)
            winner = self._select(rnd, seat, admitted, means, worlds=worlds,
                                  check_budget=check_budget,
                                  priors=[float(preferences[i]) for i in chosen])
            # the optional doomed-throw swap changes only the cards played, never the
            # selection (``selected_index`` and ``value_means`` still describe the search)
            played = self._swap_doomed_throw(rnd, seat, admitted[winner], worlds, check_budget)
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
            "value_evaluations": evaluations,
            "anchor_selected": winner == 0, "encoder_version": self.version,
            # ``played`` is the server's record/play contract (`api.server._log_play`)
            "played": list(played),
            "seconds": time.perf_counter() - started, "work_complete": True,
            **self._admission_record(),
            **self._sampler_record(),
            **self._tiebreak_record(),
            **self._lead_tiebreak_record(),
            **self._doomed_throw_record(),
            **self._adaptive_worlds_record(),
        }
        return list(played)

    # -- the optional unresolved-decision evidence rule (class docstring) ---------

    def _adaptive_worlds_decision(self, rnd, seat, admitted, worlds, started, check_budget,
                                  priors):
        """``(means, batches, winner, played, evaluations)`` under
        ``adaptive_worlds``; sets ``self._adaptive_worlds`` (the record fields).

        Control flow (#936 HOLD: optional work must never cost the completed
        base search):
        1. the base pass and the base FINALIZATION exactly as the flag-off path
           (the pre-success hard check, `_select` and `_swap_doomed_throw` on the
           base worlds) -- a failure here is a base failure and takes the normal
           fallback in `_decide_play`;
        2. only on an unresolved decision begun below ``START_FRACTION`` of the
           budget: the extra rounds and the re-selection on the combined worlds,
           every check under ``guard`` (the hard budget first, then the soft
           deadline);
        3. a final hard check before the 4W decision is published.
        ANY ``Exception`` in 2-3 -- the soft deadline, the hard budget (raised,
        or absorbed and reported by a rule that abandons itself on it), an
        error -- abandons the optional stage: the per-decision rule records are
        restored to the base finalization's snapshot and the cached base
        decision is returned, ``work_complete`` True.  ``BaseException``
        propagates.  The sampler stream is NOT rewound on an abandon (the
        record's ``adaptive_worlds_sampler_advanced`` says it moved); the
        fallback path's rewind for a genuine base failure is unchanged.
        """
        n_worlds, n_admitted = len(worlds), len(admitted)
        matrix = np.full((n_worlds, n_admitted), np.nan, dtype=np.float64)
        # serving's loop and accumulator; ``capture`` is additive (`_score_leaves`)
        sums, batches = self._score_leaves(rnd, seat, admitted, worlds, check_budget,
                                           capture=matrix)
        means = sums / n_worlds   # serving's reducer
        evaluations = n_worlds * n_admitted
        state = {"adaptive_worlds_triggered": False, "adaptive_worlds_total": n_worlds,
                 "adaptive_worlds_margin": None, "adaptive_worlds_se": None,
                 "adaptive_worlds_skipped_budget": False,
                 "adaptive_worlds_abandoned": False, "adaptive_worlds_changed": False,
                 "adaptive_worlds_played_changed": False,
                 "adaptive_worlds_sampler_advanced": False,
                 "adaptive_worlds_base_seconds": None}
        self._adaptive_worlds = state
        triggered, best = False, None
        if n_admitted >= 2 and n_worlds >= 2:
            if not np.isfinite(matrix).all():
                raise PVSearchPolicyError("adaptive_worlds value matrix has unfilled cells",
                                          stage="adaptive_worlds_matrix")
            best = int(np.argmax(means))
            runner = max((i for i in range(n_admitted) if i != best),
                         key=lambda i: (means[i], -i))
            margin = float(means[best] - means[runner])
            se = float(np.std(matrix[:, best] - matrix[:, runner], ddof=1) / math.sqrt(n_worlds))
            triggered = bool(margin < ADAPTIVE_WORLDS_Z * se or (se == 0.0 and margin == 0.0))
            state.update(adaptive_worlds_triggered=triggered, adaptive_worlds_margin=margin,
                         adaptive_worlds_se=se)
        # 1. the base finalization, exactly the flag-off path
        if check_budget is not None:
            check_budget()   # pre-success: nothing past the deadline is published
        winner = self._select(rnd, seat, admitted, means, worlds=worlds,
                              check_budget=check_budget, priors=priors)
        played = self._swap_doomed_throw(rnd, seat, admitted[winner], worlds, check_budget)
        base = (means, batches, winner, played, evaluations)
        base_elapsed = time.perf_counter() - started
        state["adaptive_worlds_base_seconds"] = base_elapsed
        if not triggered:
            return base
        budget = self.serving_budget_seconds
        if budget is not None and base_elapsed >= ADAPTIVE_WORLDS_START_FRACTION * budget:
            state["adaptive_worlds_skipped_budget"] = True
            return base
        # the finalized base decision's rule records, restored on an abandon;
        # every check in the stage latches (`optional_stage`)
        stage = OptionalStage(
            self, ADAPTIVE_WORLDS_RULE_STATE,
            hard_check=check_budget if budget is not None else None,
            budget_errors=PVSearchBudgetExceeded,
            soft_deadline=(started + ADAPTIVE_WORLDS_SOFT_FRACTION * budget
                           if budget is not None else None),
            clock=lambda: time.perf_counter(), soft_error=_AdaptiveWorldsExpired,
            final_check=check_budget, abandon_on=Exception,
            # `_worlds` overwrites the sampler record; the record describes the base draw
            restore_always=("_last_sampling",))
        guard = stage.guard
        total_sums, extra_worlds, extra_batches, extra_evaluations = sums.copy(), [], 0, 0
        with stage:
            # 2. the optional stage
            for _ in range(ADAPTIVE_WORLDS_EXTRA_ROUNDS):
                state["adaptive_worlds_sampler_advanced"] = True
                drawn, _attempts = self._worlds(rnd, seat, guard)
                round_sums, round_batches = self._score_leaves(rnd, seat, admitted, drawn, guard)
                extra_evaluations += len(drawn) * n_admitted
                extra_batches += round_batches
                total_sums = total_sums + round_sums
                extra_worlds.extend(drawn)
            if guard is not None:
                guard()
            combined = list(worlds) + extra_worlds
            combined_means = total_sums / len(combined)
            combined_winner = self._select(rnd, seat, admitted, combined_means, worlds=combined,
                                           check_budget=guard, priors=priors)
            combined_played = self._swap_doomed_throw(rnd, seat, admitted[combined_winner],
                                                      combined, guard)
            # 3. an expiry a rule absorbed abandons; nothing past the hard
            # deadline is published
            stage.publish()
        if stage.abandoned:
            state.update(adaptive_worlds_abandoned=True,
                         adaptive_worlds_abandon_reason=stage.reason,
                         adaptive_worlds_abandon_error=stage.error,
                         adaptive_worlds_abandoned_evaluations=extra_evaluations)
            return base
        state.update(adaptive_worlds_total=len(combined),
                     adaptive_worlds_changed=int(np.argmax(combined_means)) != best,
                     adaptive_worlds_played_changed=list(combined_played) != list(played))
        return (combined_means, batches + extra_batches, combined_winner, combined_played,
                evaluations + extra_evaluations)

    def _adaptive_worlds_record(self):
        if not (self.adaptive_worlds or self.adaptive_worlds_leads) \
                or self._adaptive_worlds is None:
            return {}
        return dict(self._adaptive_worlds)

    def _sampler_record(self):
        """The refusal rule's fields for the decision record: present only while
        the rule is on (zeros when no refusal constrained this decision)."""
        if not self.refusal_constraints:
            return {}
        return {"refusal_observations": 0, "refusal_rejections": 0,
                "refusal_fallback_worlds": 0, "refusal_pinned_codes": 0,
                **self._last_sampling}

    def _sampler_counts(self):
        return {name: int(getattr(self.sampler, name, 0)) for name in SAMPLER_DELTA_COUNTERS}

    def decide_play(self, rnd, seat):
        started = time.perf_counter()
        counts = self._sampler_counts()
        try:
            return self._decide_play(rnd, seat, started)
        finally:
            self.search_secs += time.perf_counter() - started
            # #707 S9, telemetry only: this decision's change in the sampler's
            # cumulative void counters (worlds assigned ignoring public voids
            # with SHENGJI_REQUIRE_VOIDS unset; worlds refused under it).  Reads
            # the counters; never samples, draws or alters the decision.
            record = self.last_decision_record
            if isinstance(record, dict):
                after = self._sampler_counts()
                for name in SAMPLER_DELTA_COUNTERS:
                    record[f"{name}_delta"] = after[name] - counts[name]

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
                # #707 S9: the raise site and the bounded message, so a
                # search-error is identifiable from the serving log alone
                "error_stage": getattr(exc, "stage", None),
                "error_message": str(exc)[:ERROR_MESSAGE_MAX],
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
                       bury_serving_budget_seconds=None, tree: PVTreeConfig | None = None,
                       bot_factory=None, prior_checkpoint: str | None = None,
                       prior_sha256: str | None = None,
                       refusal_constraints: bool = SAMPLER_DEFAULTS["refusal_constraints"],
                       refusal_event_complete: bool = SAMPLER_DEFAULTS["refusal_event_complete"],
                       admission_diversity: bool = ADMISSION_DEFAULTS["admission_diversity"],
                       admit_forced_single: bool = ADMISSION_DEFAULTS["admit_forced_single"],
                       tiebreak_points: bool = TIEBREAK_DEFAULTS["tiebreak_points"],
                       adaptive_k: bool = ADAPTIVE_K_DEFAULTS["adaptive_k"],
                       lead_anchor: bool = LEAD_ANCHOR_DEFAULTS["lead_anchor"],
                       lead_tiebreak_prior: bool = LEAD_TIEBREAK_DEFAULTS["lead_tiebreak_prior"],
                       doomed_throw_swap: bool = DOOMED_THROW_DEFAULTS["doomed_throw_swap"],
                       small_joker_guard: bool = SMALL_JOKER_GUARD_DEFAULTS["small_joker_guard"],
                       adaptive_worlds: bool = ADAPTIVE_WORLDS_DEFAULTS["adaptive_worlds"],
                       adaptive_worlds_leads: bool = ADAPTIVE_WORLDS_DEFAULTS["adaptive_worlds_leads"],
                       wide_lead_admission: bool = WIDE_LEAD_DEFAULTS["wide_lead_admission"],
                       doomed_throw_reselect: bool = DOOMED_THROW_RESELECT_DEFAULTS["doomed_throw_reselect"]
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
    config = PVSearchConfig(checkpoint_sha256=sha256, tree=tree, worlds=int(worlds), candidates=int(candidates),
                            cap=int(cap), batch_size=int(batch_size),
                            serving_budget_seconds=_serving_budget(serving_budget_seconds),
                            refusal_constraints=refusal_constraints,
                            refusal_event_complete=refusal_event_complete,
                            admission_diversity=admission_diversity,
                            admit_forced_single=admit_forced_single,
                            tiebreak_points=tiebreak_points, adaptive_k=adaptive_k,
                            lead_anchor=lead_anchor,
                            lead_tiebreak_prior=lead_tiebreak_prior,
                            doomed_throw_swap=doomed_throw_swap,
                            small_joker_guard=small_joker_guard,
                            adaptive_worlds=adaptive_worlds,
                            adaptive_worlds_leads=adaptive_worlds_leads,
                            wide_lead_admission=wide_lead_admission,
                            doomed_throw_reselect=doomed_throw_reselect)
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
    if config.tree is not None:
        # the tree's classes subclass the served ones (lazy: that module imports this one)
        from .pv_tree_search import tree_bot_class
        build = tree_bot_class(expected, bot_factory)
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
                        tree: PVTreeConfig | None = None,
                        prior_checkpoint: str | None = None,
                        prior_sha256: str | None = None,
                        refusal_constraints: bool = SAMPLER_DEFAULTS["refusal_constraints"],
                        refusal_event_complete: bool = SAMPLER_DEFAULTS["refusal_event_complete"],
                        admission_diversity: bool = ADMISSION_DEFAULTS["admission_diversity"],
                        admit_forced_single: bool = ADMISSION_DEFAULTS["admit_forced_single"],
                        tiebreak_points: bool = TIEBREAK_DEFAULTS["tiebreak_points"],
                        adaptive_k: bool = ADAPTIVE_K_DEFAULTS["adaptive_k"],
                        lead_anchor: bool = LEAD_ANCHOR_DEFAULTS["lead_anchor"],
                        lead_tiebreak_prior: bool = LEAD_TIEBREAK_DEFAULTS["lead_tiebreak_prior"],
                        doomed_throw_swap: bool = DOOMED_THROW_DEFAULTS["doomed_throw_swap"],
                        small_joker_guard: bool = SMALL_JOKER_GUARD_DEFAULTS["small_joker_guard"],
                        adaptive_worlds: bool = ADAPTIVE_WORLDS_DEFAULTS["adaptive_worlds"],
                        adaptive_worlds_leads: bool = ADAPTIVE_WORLDS_DEFAULTS["adaptive_worlds_leads"],
                        wide_lead_admission: bool = WIDE_LEAD_DEFAULTS["wide_lead_admission"],
                        doomed_throw_reselect: bool = DOOMED_THROW_RESELECT_DEFAULTS["doomed_throw_reselect"]
                        ) -> dict:
    """``{name: factory}`` for one recipe; the factory takes ``seed=`` from `make_bot`.
    With ``bury_arm`` the name carries the bury identity exactly as the shortlist's
    bury wrapper does: ``<play name>-bury-<arm>-<12 hex of the cwv-bury-recipe-v1 identity>``."""
    from ..ai.cwv_policy import checkpoint_id
    config = PVSearchConfig(checkpoint_sha256=sha256, tree=tree, worlds=int(worlds), candidates=int(candidates),
                            cap=int(cap), batch_size=int(batch_size),
                            serving_budget_seconds=_serving_budget(serving_budget_seconds),
                            refusal_constraints=refusal_constraints,
                            refusal_event_complete=refusal_event_complete,
                            admission_diversity=admission_diversity,
                            admit_forced_single=admit_forced_single,
                            tiebreak_points=tiebreak_points, adaptive_k=adaptive_k,
                            lead_anchor=lead_anchor,
                            lead_tiebreak_prior=lead_tiebreak_prior,
                            doomed_throw_swap=doomed_throw_swap,
                            small_joker_guard=small_joker_guard,
                            adaptive_worlds=adaptive_worlds,
                            adaptive_worlds_leads=adaptive_worlds_leads,
                            wide_lead_admission=wide_lead_admission,
                            doomed_throw_reselect=doomed_throw_reselect)
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
                               bot_factory=bot_factory, tree=config.tree,
                               prior_checkpoint=prior_checkpoint,
                               prior_sha256=prior_sha256,
                               refusal_constraints=config.refusal_constraints,
                               refusal_event_complete=config.refusal_event_complete,
                               admission_diversity=config.admission_diversity,
                               admit_forced_single=config.admit_forced_single,
                               tiebreak_points=config.tiebreak_points,
                               adaptive_k=config.adaptive_k,
                               lead_anchor=config.lead_anchor,
                               lead_tiebreak_prior=config.lead_tiebreak_prior,
                               doomed_throw_swap=config.doomed_throw_swap,
                               small_joker_guard=config.small_joker_guard,
                               adaptive_worlds=config.adaptive_worlds,
                               adaptive_worlds_leads=config.adaptive_worlds_leads,
                               wide_lead_admission=config.wide_lead_admission,
                               doomed_throw_reselect=config.doomed_throw_reselect),
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
    optional ``_ADMISSION_DIVERSITY`` / ``_ADMIT_FORCED_SINGLE`` / ``_REFUSAL_CONSTRAINTS`` /
    ``_REFUSAL_EVENT_COMPLETE`` / ``_TIEBREAK_POINTS`` / ``_ADAPTIVE_K`` / ``_LEAD_ANCHOR`` / ``_LEAD_TIEBREAK_PRIOR`` /
    ``_DOOMED_THROW_SWAP`` / ``_SMALL_JOKER_GUARD`` / ``_ADAPTIVE_WORLDS`` / ``_ADAPTIVE_WORLDS_LEADS`` /
    ``_WIDE_LEAD_ADMISSION`` / ``_DOOMED_THROW_RESELECT`` rule flags (``0`` or ``1`` only; unset or empty is
    off), as keyword arguments for
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
    for suffix, key in RULE_FLAGS.items():
        raw = env.get(ENV_PREFIX + suffix)
        if raw in (None, ""):
            continue
        if raw not in ("0", "1"):
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} must be 0 or 1, not {raw!r}")
        if raw == "1":
            recipe[key] = True
    tree = tree_env(env, ENV_PREFIX)   # SHENGJI_PV_TREE_SIMS (+ _CONT / _EPS / _ZMIN / ...)
    if tree is not None:
        recipe["tree"] = tree
    arm = env.get(ENV_PREFIX + "BURY_ARM")
    if arm:
        arm = BURY_ARM_ALIASES.get(arm, arm)
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
