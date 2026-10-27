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

Optional small-endgame lead scoring, OFF BY DEFAULT:
``SHENGJI_PV_EXACT_LEAD_ENDGAME=1`` keeps the completed baseline ballot and
sampled worlds, then replaces value-head scores with exact partnership minimax
continuations after the existing first-trick leaf when every hand has <=4 cards.
Only a complete all-candidate/all-world pass may replace baseline scores; a
node cap, error or deadline preserves the finalized baseline decision. This
is sampled-world perfect-information continuation, not an imperfect-information
solution. Limits are recipe-pinned; tree/adaptive/oracle combinations are refused.
Two independent variants, each OFF BY DEFAULT and refused without
``SHENGJI_PV_EXACT_LEAD_ENDGAME=1``:
``SHENGJI_PV_EXACT_LEAD_TIE_BASELINE=1`` (token ``elt``) keeps the finalized
baseline lead unless the exact-selected lead's exact mean is STRICTLY higher
than the exact mean of the baseline's selected candidate.  The comparison is
exact float equality: every exact mean is a sum of half-integer level
categories over the worlds divided by the world count, so equal sums are
bit-equal and no epsilon is needed (a tolerance could only merge genuinely
different means).  ``SHENGJI_PV_EXACT_LEAD_POLICY_FIRST=1`` (token ``elp``)
completes the first trick's three responses with the served policy head's
argmax, each responder encoded on worlds sampled from its own view
(`exact_lead_policy_first`), instead of the heuristic; the exact solve after
that trick is unchanged.  Both run inside the same exact-lead stage, deadline
and fallback.
A further rule, OFF BY DEFAULT and refused without it:
``SHENGJI_PV_EXACT_DEEP_CARDS=<n>`` (``exact_deep_cards``, n in 4..8, token
``ed<n>``) admits leads where every hand holds at most n cards and scores them
with level-mode sessions (`pv_exact_deep.exact_root_means`): the minimax value
resolved only up to the signed-level steps the means use, so the means are a
full minimax's, at a per-world node cap of ``EXACT_DEEP_LIMITS['max_nodes']``
instead of 10000; the start gate, deadline and fallback are the exact lead's.
Two DEV caps exist for a ceiling measurement that lifts those limits:
``SHENGJI_PV_EXACT_LEAD_MAX_SECONDS`` (the stage deadline, default
``EXACT_LEAD_LIMITS['max_seconds']``, token ``els<ms>``) and
``SHENGJI_PV_EXACT_DEEP_MAX_NODES`` (default ``EXACT_DEEP_LIMITS['max_nodes']``,
token ``edn<nodes>``).  At their defaults they enter neither the name nor the
digest; any other value replaces the constant in the digested limits.  The
serving budget's start gate and soft deadline still apply, so a ceiling run also
raises ``SHENGJI_PV_SERVING_BUDGET_SECONDS``.
Follow decisions take the separate ``exact_follow`` stage (`pv_exact_follow`).

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

Optional history-legal world test (board row S27), OFF BY DEFAULT:
``SHENGJI_PV_WORLD_HISTORY_LEGAL=1`` rejects and redraws a sampled play world
in which some earlier follow by another seat would have been illegal for the
hand that world gives the seat at that moment (its hand now plus every card it
has played since), by the engine's own `validate_follow`
(`ai.history_legality`).  `Memory`'s pair and run caps bound only the current
hand, so without the test a world can give a seat one copy of a card whose twin
it played later, which means it held a pair it was obliged to follow with.  The
test applies for at most ``HISTORY_ATTEMPT_FACTOR`` (8) attempts per world;
worlds still missing after that are drawn exactly as without the rule (the
refusal test still applies when the refusal rule is on) and counted in the
record's ``history_fallback_worlds``.  It combines with the refusal rule and
is refused with the oracle diagnostics (whose worlds bypass the sampler).
``0`` or ``1`` only; on, it enters the recipe digest and adds ``-whl`` to the
name right after the refusal tokens, and the decision record gains
``history_follow_events``, ``history_rejections``,
``history_rejections_by_age`` (tricks back from the current one, of the first
violated follow) and ``history_fallback_worlds``; off, every existing name,
digest, sampled world and decision record is unchanged.
Its draw-time form, ``SHENGJI_PV_WORLD_HISTORY_DRAW=1`` (requires the test; name
token ``-whd`` after ``-whl``), deals no seat the twin of a card it played at or
after a follow that showed fewer pairs than were led
(`ai.history_legality.draw_constraints`), so the pair obligation needs no
rejection; the test still checks every world (the tractor obligation stays
with it).  The record gains ``history_draw_constraints`` and
``history_draw_forbidden``.

Optional belief proposal inside the history-legal test (board row S17), OFF BY
DEFAULT: ``SHENGJI_PV_BELIEF_WORLDS=1`` with ``SHENGJI_PV_BELIEF_CKPT`` and
``SHENGJI_PV_BELIEF_SHA256`` (a ``shengji-belief-numpy-v1`` package, hash-pinned;
`ai.belief_numpy`) makes the history-legal draw take its hands from the S17
history belief model: per-card receiver marginals from the round's public
history, projected to the receiver sizes and drawn copy by copy so sizes,
public voids and public pins hold exactly (`BeliefProposal`), then the same
completion, refusal test and history test as ``-whl``; the proposal also never
deals a seat a card `ai.history_legality.draw_constraints` forbids it (the
draw-time form ``-whd`` applies to the production draw only, so a proposal
honours it itself).  It requires ``SHENGJI_PV_WORLD_HISTORY_LEGAL=1`` and
``SHENGJI_PV_WORLD_HISTORY_DRAW=1``.  Any error other than the serving budget
(no package, a featurizer or model failure, a preparation over
``belief_numpy.PREP_SECONDS``) falls back, for that decision, to the
history-legal production draw and is recorded (``belief_fallback``,
``belief_error``).  ``0`` or ``1`` only; on, the recipe digest gains the
package's sha256 and the proposal's identity, the name gains ``-bw`` right
after ``-whd``, and the decision record gains ``belief_fallback``,
``belief_proposed`` and ``belief_ms``; off, every existing name, digest, sampled
world and record is unchanged.
Its capacity-aware draw (board row S34), OFF BY DEFAULT:
``SHENGJI_PV_BELIEF_CAPACITY=1`` (requires the proposal; name token ``-bwc``
after ``-bw``) makes the proposal draw each copy with its receiver weights
scaled by open slots over expected remaining demand
(`train.belief_seq.sample_worlds_capacity`), so a receiver its likely copies
under-fill -- a non-banker's hidden kitty, which the marginals give almost no
trump mass -- is no longer filled at the end with whatever is left.  Only the
draw changes: the same package, marginals, projection, constraints,
completion, tests, fallback and record.  ``0`` or ``1`` only; on, the recipe
digest names the capacity proposal (``belief_worlds_package.proposal``); off,
the proposal's name, digest, worlds and record are exactly what they were.

Its log, ON BY DEFAULT while the proposal is on: ``SHENGJI_PV_BELIEF_LOG`` (``0``
or ``1``; unset is ``1``) adds ``belief_log`` and, per drawn proposal, the
proposal's seed ``belief_seed`` (the one draw it takes from the sampler stream;
the proposal's worlds are a function of it and the public state), the round's
refusal ledger ``belief_refusals`` when it is non-empty, the model's marginals
as a uint8 snapshot ``belief_snapshot`` (`belief_numpy.encode_snapshot`) and
their summary (``belief_entropy_bits``, ``belief_top_mass``,
``belief_hidden_copies``).  It only reads what the draw computed: no name,
digest, draw or decision depends on it (`scripts/belief_debug.py` replays a
logged decision's worlds).

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

Optional late-hand finish admission, OFF BY DEFAULT:
``SHENGJI_PV_FINISH_LEAD_ADMISSION=1`` adds at most ONE whole-hand lead when
2--8 remaining cards share an effective suit and the unchanged ballot omits it.
It preserves the anchor and all existing admitted actions, including forced
extras. The capped pool also retains this candidate. Normal engine throw
resolution, value scoring and selection still apply: it is NOT a must-play
or a claim that the throw will stand. At W64 the extra value work is at most
64 leaves with fixed W64, versus 1536 for widening K8 to K32. Local/host time still needs
measurement. Off, the recipe/name/record do not change; on, the name adds
``-fla`` and the recipe pins the eight-card limit. Tree combinations are refused.

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

Its optional exact-stage guard, OFF BY DEFAULT:
``SHENGJI_PV_DOOMED_THROW_RESELECT_EXACT_GUARD=1`` (token ``dtrx``, after ``dtr``;
requires ``SHENGJI_PV_DOOMED_THROW_RESELECT=1`` and ``SHENGJI_PV_EXACT_LEAD_ENDGAME=1``,
refused without either) -- the re-select never discards exact value: on the
exact lead stage's selection over its exact means it may move only to a
candidate whose exact mean is not below the selected candidate's (a tie by
exact float equality keeps the re-select's benefit; definition, record and the
skipped doomed test: `policy_value_search`).  The base pass and an ineligible,
skipped or abandoned exact stage re-select exactly as ``dtr`` does.  ``0`` or
``1`` only; on, it enters the recipe digest with ``doomed_throw_reselect_exact_rule``
(`DOOMED_THROW_RESELECT_EXACT_RULE`) and adds ``-dtrx`` to the name.  Off, it
is absent from the payload, so the release-46 name and every decision are
unchanged.  It adds no work: it masks candidates the re-select would have
tested and skips the doomed test when nothing could replace the selection.

Optional value-leaf rule, OFF BY DEFAULT: ``SHENGJI_PV_LEAF_GREEDY_FINISH=1``
(token ``lgf``, after ``lpft``) -- the leaf the value head scores is the
afterstate with the current trick finished by the tree's ``trick-greedy``
finisher (R = `LEAF_GREEDY_REPLIES`) instead of the heuristic, in every
sampled world; the admission, the selection rules, the exact stages and the
played action are what they were (definition, cost and record:
`policy_value_search`).  ``0`` or ``1`` only; on, it enters the recipe digest
with ``leaf_finish`` (`LEAF_GREEDY_FINISH_RULE`) and adds ``-lgf`` to the name.
Off, it is absent from the payload, so every existing name and every decision
are unchanged.  Not combined with the tree or the adaptive worlds rule (refused).

Its optional exact-stage yield, OFF BY DEFAULT:
``SHENGJI_PV_LEAF_GREEDY_FINISH_EXACT_SKIP=1`` (token ``lgfx``, after ``lgf``;
requires ``SHENGJI_PV_LEAF_GREEDY_FINISH=1`` and an exact stage,
``SHENGJI_PV_EXACT_LEAD_ENDGAME=1`` or ``SHENGJI_PV_EXACT_FOLLOW=1``, refused
otherwise) -- on a decision an exact stage is eligible for (the stage's own
gate, `PVSearchBot._exact_lead_gate` / `_exact_follow_eligible`, before any
budget check) the value pass scores the plain heuristic leaf (`_leaf`), so the
base pass costs what it does without ``lgf`` and the exact stage keeps its
start share of the budget; on every other decision ``lgf`` applies unchanged.
The tie-break prices the same leaf the pass scored.  ``0`` or ``1`` only; on,
it enters the recipe digest with ``leaf_finish_exact_rule``
(`LEAF_GREEDY_EXACT_SKIP_RULE_ID`) and adds ``-lgfx`` to the name; the record
gains ``leaf_greedy_finish_exact_skipped`` (only with the flag on).  Off, it is
absent from the payload, so every existing name and every decision are unchanged.

Its optional deadline, OFF BY DEFAULT and a search-policy change where it
fires: ``SHENGJI_PV_LEAF_GREEDY_DEADLINE=<seconds>`` (``leaf_greedy_deadline_ms``,
whole ms in [1, 60000]; unset, empty or ``0`` is off; requires ``lgf``) -- the
finish checks the decision's elapsed time (from the start the serving budget
measures) before every ply, every value batch and every clone of a ply; once
it has passed the deadline the finish stops and every leaf of the decision,
for the value pass and the tie-break alike, is the plain heuristic leaf
(`_leaf`, the flag-off leaf).  Where it does not fire the decision is the
``lgf`` one.  The serving budget and the exact stages keep their own
deadlines.  On, it enters the recipe digest as ``leaf_greedy_deadline``
(`LEAF_GREEDY_DEADLINE_RULE_ID`) and adds ``-lgfd<ms>`` after ``lgf`` /
``lgfx``; the record gains ``leaf_greedy_deadline_fired`` and
``leaf_greedy_deadline_cut_leaves`` (only with it on).

Its optional top-m restriction, OFF BY DEFAULT and a search-policy change
where it applies: ``SHENGJI_PV_LEAF_GREEDY_TOP=<m>`` (``leaf_greedy_top``, an
int in [1, 64]; unset, empty or ``0`` is off; requires ``lgf``) -- on a
decision whose value pass would finish leaves greedily and that admits more
than ``m`` candidates, every admitted candidate is first scored on the plain
heuristic leaf (`_leaf`, the flag-off leaf, on the same worlds); only the
``m`` best by that plain mean (lowest admitted position on a tie) are then
greedy-finished and scored on the ``lgf`` leaf.  The selection rules see one
mean per admitted candidate: the ``lgf`` mean for the ``m`` kept ones, and
for each pruned one its plain mean less ``LEAF_GREEDY_TOP_OFFSET`` (a finite
offset far outside the value head's range, so a pruned candidate ranks below
every kept one and the pruned keep their plain order among themselves).
A pruned candidate's leaf is the plain leaf everywhere in the decision (the
tie-break prices it on that leaf).  With ``m`` at least the admitted count the
decision is the ``lgf`` one; where ``lgf`` does not run (``lgfx``) or the finish
passes its deadline, every leaf is the plain one, nothing is pruned and the
decision is the plain one.  `value_matrix` returns the same accumulator, so its
``sums / W`` are the served means.  On, it enters the recipe digest as ``leaf_greedy_top`` and adds
``-lgft<m>`` after the greedy leaf's tokens (``lgf``, ``lgfx``, ``lgfd<ms>``);
the record gains ``leaf_greedy_top_applied``, ``leaf_greedy_top_kept``
(admitted positions) and ``leaf_greedy_top_plain_means`` (only with it on).
Off, every existing name, digest and decision is unchanged.

The lead admission width of ``wide_lead_admission`` (`PVSearchBot` docstring):
``SHENGJI_PV_WIDE_LEAD_K=<k>`` (``wide_lead_k``, an int in [9, 64], default
``WIDE_LEAD_K`` = 32; refused without ``SHENGJI_PV_WIDE_LEAD_ADMISSION=1``).
At the default nothing changes (the payload already names 32 and the token is
``-wla``); another width replaces it in the payload and the token becomes
``-wla<k>``.

Four latency switches, OFF BY DEFAULT, that enter no name, payload or digest
(like ``SHENGJI_PV_BELIEF_LOG`` they are read from the serving environment
where the bot is built; ``0`` or ``1`` only).  On the decisions the search
completes, none changes the cards played, the sampler stream or (beyond
the skipped pass's own fields) the record:
``SHENGJI_PV_ENCODE_PREFIX_CACHE=1`` encodes the value pass's leaves, the
prior's root rows and, with ``lgf``, the greedy finish's reply valuations and
reply policy rows (`pv_encode_prefix.fused_many`, `reply_rows`: the prefix
laid down once per batch) on the decision root's shared history prefix with
one batched
validation (`pv_encode_prefix`; every tensor is the reference encoder's, byte
for byte, and anything it does not cover takes the reference path), and
``SHENGJI_PV_SINGLE_CANDIDATE_FAST=1`` skips the value pass when the admission
returns one candidate and no exact lead stage would start on it (no consumer
reads that value: the selection of one is index 0).  The worlds are still
drawn, so the sampler stream is unchanged, and the selection rules and the
doomed-throw finalization still run on them; the record then says
``single_candidate_fast`` with ``value_means`` ``[None]`` and zero value
batches and evaluations.  It does not apply with ``lgf`` or an overridden
value pass.  Two outcomes differ from the full pass: a one-candidate pass that
would have run past the serving budget, or met a non-finite value score, falls
back to the anchor without the switch and plays the selected candidate with
it.  A consumer of every candidate's value (the trajectory harvest, the M9
panel, the counterfactual value diagnostic) refuses the switch before it
starts (`require_value_means`, `refuse_single_candidate_fast_env`).
``SHENGJI_PV_LEAF_GREEDY_STREAM=1`` bounds ``lgf``'s memory: the greedy
finish's reply listings (up to ``cap`` follows per distinct hand and lead, each
with a dense float64 scoring matrix) are held as int8 card indices for one ply
at a time, and each scoring matrix is rebuilt by the same operations at its
product and dropped (`pv_tree_search.legal_replies_compact`).  The plies, their
batches, every score and every record field are the switch-off ones; without
``lgf`` nothing reads it.
``SHENGJI_PV_ENCODE_BATCH_FAST=1`` builds the prefix-cached batches (the value
pass's leaves and ``lgf``'s reply valuations and reply policy rows) with
`pv_encode_prefix.fused_many_batched`: the same tensors byte for byte and the
same rows kept or refused, with the world planes indexed from the distinct
hands and the v2/v7 columns assembled as arrays.  Without
``SHENGJI_PV_ENCODE_PREFIX_CACHE=1`` nothing reads it.
``SHENGJI_PV_LEAF_CACHE_RELEASE=1`` empties ``lgf``'s finished-leaf cache
when a decision ends.  `_search` starts every decision with a fresh cache, so
no decision reads an earlier one's leaves; without the switch the up to
W x K finished rounds stay on the bot, and the server deep-copies the bot
(and them) before every bury and play turn.
``SHENGJI_PV_LEAF_CLONE_FAST=1`` builds ``lgf``'s clones and reply children
(`pv_tree_search.afterstate_fast`, `child_position_fast`) with a shallow copy
that is ``copy.copy``'s own result for an exact `Round` under the default copy
protocol (``copy.copy`` otherwise): the same objects, attribute for attribute.
``SHENGJI_PV_LEAF_TRICK_CACHE=1`` gives ``lgf``'s clones of a FOLLOW root the
trusted trick caches (incumbent, running points; `pv_tree_search.seed_trick_caches`)
a lead root's clones get from their own lead, folded over the trick's plays by
the same rule `Round.play` folds them, so their finishing plays take the
trusted rollout paths a lead root's already take.  The winners, points and
heuristic replies are the recomputed ones.
``SHENGJI_PV_WORLD_FAST=1`` speeds up the belief-proposed world draw: the
proposal's copy loop compiled on the same generator and each world completed
against the decision's played cards counted once (`pv_native`): the same
worlds, the same generator and sampler states.
``SHENGJI_PV_ENCODE_NATIVE=1`` builds those batches with the compiled
`pv_encode_prefix.fused_many_native`: `fused_many_batched`'s tensors byte for
byte, every batch the kernel declines (a row the batched builder would skip
or refuse) built by `fused_many_batched` itself.  Without
``SHENGJI_PV_ENCODE_BATCH_FAST=1`` (or the compiled module) nothing reads it.
``SHENGJI_PV_LEGAL_NATIVE=1`` builds ``lgf``'s follow listings with the
compiled `pv_native.follow_listing`: the same actions in the same order as
the Python enumeration, stored as `pv_tree_search.CompactReplies`; without the
compiled module the Python listing runs.  Without
``SHENGJI_PV_LEAF_GREEDY_STREAM=1`` nothing reads it.

The exact stages' world subset, OFF BY DEFAULT and a search-policy change
where it applies: ``SHENGJI_PV_EXACT_WORLD_SUBSET=<n>`` (an int in [1, 512];
unset, empty or ``0`` is off) has the exact lead and exact follow stages solve
the first ``n`` sampled worlds in draw order, equally weighted, when more than
``n`` are drawn (every admitted candidate on the same subset); the value pass,
the selection rules and the doomed-throw test still read every world, and an
abandoned stage keeps the complete baseline as before.  With ``n`` at least
``SHENGJI_PV_WORLDS`` it is the same search and absent from the payload and
the name; narrower, it needs an exact stage (refused otherwise), enters the
payload as ``exact_world_subset`` and adds ``-exs<n>`` after the exact follow
tokens, and the stage records gain ``exact_lead_subset_worlds`` /
``exact_follow_subset_worlds``.

Optional declaration rule, OFF BY DEFAULT: ``SHENGJI_PV_VALUE_DECLARE=1`` --
the trump declaration is chosen with the value head instead of the inherited
heuristic count (`HeuristicBot.decide_declare`, unchanged and still computed
first as the base decision).  Only where the heuristic would DECLARE now, or in
the final grace window (``final=True``), every declare option plus PASS is
scored on ``SHENGJI_PV_VALUE_DECLARE_WORLDS`` (default 64) sampled complete
deals by the value head from the seat's team (world model:
`value_declare`), and the argmax replaces the heuristic's choice only when it
beats it by more than ``SHENGJI_PV_VALUE_DECLARE_MARGIN`` (default 0.0, in the
head's units: expected signed levels).  The evaluation runs as an
`optional_stage.OptionalStage` under the per-decision serving budget
(``SHENGJI_PV_SERVING_BUDGET_SECONDS``); an expiry or any error abandons it to
the heuristic's choice and is recorded (definition, gate and record:
`PVSearchBot.decide_declare`).  ``0`` or ``1`` only; its two parameters are
refused while it is off (a parameter with no effect would still enter no
identity); on, it enters the recipe digest with its parameters and its model
and adds ``-vd`` to the name as the last rule token.  It combines with every
play rule (they never see a declaration decision).  Off, it is absent from the
payload, so every existing name (release 42 above) and every decision are
unchanged, and ``decide_declare`` IS the heuristic's.

Its first-round gate widening (#707 "Declare-frequency diagnostic"), OFF BY
DEFAULT: ``SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST=1`` -- in a round with no fixed
banker (``rnd.banker is None``: the game's first round, where the first
declarer takes the bank) the value-declare gate admits EVERY declare chance at
which the seat has an option (`Round.declare_options` non-empty), not only the
chances where the heuristic would declare or the grace window; in a round with
a fixed banker the gate is exactly ``value_declare``'s.  Only the gate changes
(`PVSearchBot.declare_gate`, the single source of truth the server's off-loop
admission reads too): the candidate set, the world model, the worlds, the
margin, the argmax and tie rule and every fallback are ``value_declare``'s.
The record gains ``gate`` (``"heuristic"`` / ``"final"`` / ``"every_first"``:
why the chance was admitted; ``final`` and a heuristic declaration keep their
names, so ``every_first`` counts exactly the chances this flag added).  ``0``
or ``1`` only; it REQUIRES ``SHENGJI_PV_VALUE_DECLARE=1`` (refused otherwise: a
gate for a rule that is off admits nothing); on, it enters the recipe digest
and adds ``-vdef`` to the name immediately after ``-vd``.  Off, it is absent
from the payload, so every existing name and every decision are unchanged.

Its served-bury world model (#707 S15(2)), OFF BY DEFAULT:
``SHENGJI_PV_VALUE_DECLARE_SERVED_BURY=1`` -- the declaration's world banker
buries with the bot's served chooser (the wide value-only bury, ``bwv``) instead
of the heuristic bury, so a declaration is valued by the bury the bot would
make (`declare_served_bury`).  The ordinary pass (every outcome, heuristic bury,
``value_declare_worlds`` worlds) runs first and nominates ONE challenger, the
best outcome other than the heuristic's; those two outcomes are then scored on
the first 16 worlds of the same stream, each with the heuristic bury and with
the served chooser at a reduced width (16 candidates x 8 banker-view worlds;
served: 64 x 32), and compared by the control-variate means ``ordinary +
(served-bury - heuristic-bury)``; the margin test is unchanged.  Cost
(release 45's package, Mini, compiled engine): the reduced chooser is ~14 ms a
bury against the served width's ~190 ms, so the pass adds about 32 buries,
~0.45 s, per evaluated declare chance.  ``0`` or ``1`` only; it REQUIRES
``SHENGJI_PV_VALUE_DECLARE=1`` and the served wide chooser
(``SHENGJI_PV_BURY_ARM=hybrid|value`` with ``SHENGJI_PV_BURY_WIDE_VALUE=1``),
refused otherwise; on, it enters the recipe digest (``value_declare_model``
names the served bury, and the four reduced parameters) and adds ``-vdsb`` to
the name after ``-vdef``.  The record gains ``served_bury`` (``ordinary_choice``,
``challenger``, the widths, ``worlds_completed``, the three mean pairs,
``seconds``); ``heuristic_mean`` and ``best_mean`` are then the adjusted means
the margin test used, ``outcome_means`` stays the ordinary pass's.  Off, it is
absent from the payload, the record and the instance state, so every existing
name and every decision are unchanged.
Its pass-conditioned world model (#707 S15(4)), OFF BY DEFAULT:
``SHENGJI_PV_VALUE_DECLARE_PASS_WORLDS=1`` -- each declare world is drawn from
the uniform posterior and ACCEPTED with the likelihood of the other seats'
silence (`declare_pass_worlds`): a seat that in that world has held a
combination stronger than the current declaration for ``d`` of its own dealt
cards, and has not declared, contributes ``(1 - 0.02) ** d``; the deciding seat
and the current declarer contribute 1 (0.02 is an exploratory fixed constant,
not a calibrated rate).  A soft weight, not an exclusion: in the production
logs humans passed an over-declaring pair to the end of the window in 39 of 64
episodes.  At most 32 draws per world; after that the last (rejected, so not
uniform) draw is kept as a counted fallback.  The candidate set, the leaves, the worlds
count, the margin and every fallback are ``value_declare``'s.  ``0`` or ``1``
only; it REQUIRES ``SHENGJI_PV_VALUE_DECLARE=1`` (refused otherwise); on, it
enters the recipe digest (``value_declare_model`` names
``pass-conditioned-unseen``, with the hazard and the attempt cap) and adds
``-vdpw`` to the name after ``-vdef`` and ``-vdsb``.  The record gains ``pass_worlds``
(``hazard``, ``max_attempts``, ``worlds``, ``attempts``, ``fallbacks``).  Off,
it is absent from the payload, the record and the instance state, so every
existing name and every decision are unchanged.

Its wait option (#707 S15), OFF BY DEFAULT: ``SHENGJI_PV_VALUE_DECLARE_WAIT=1``
-- when the value declaration has decided to DECLARE at a chance during the
deal (``final=False``; never in the grace window, never when it passes), a
second `OptionalStage` compares declaring now with staying silent now
(`declare_wait`): on the first 32 draws of the ordinary pass's stream that pass
a current-standing heuristic consistency filter (no other seat would declare
now against the standing declaration; not a likelihood of their past silence;
uniform draws even under ``vdpw``; at most 256 draws), both branches play out the rest of the deal with every other seat declaring by the
heuristic, the bot silent; at the deal's end the bot makes one choice among
its legal options and PASS by the value head's mean over 8 worlds sampled from
its own end-of-deal view, and that outcome is scored in the outer world.  The
bot waits (returns PASS) only when the WAIT mean beats the NOW mean by more
than ``value_declare_margin``; it is asked again at its next card.  An expiry
or error abandons the stage to the value declaration's choice (not the
heuristic's).  Cost (release 45's package, Mini, compiled engine, 200 seeded
deals): +0.135 s mean, max 0.43 s per wait pass, inside the 3 s budget.  ``0`` or
``1`` only; it REQUIRES ``SHENGJI_PV_VALUE_DECLARE=1``
(refused otherwise); on, it enters the recipe digest (``value_declare_wait_model``
and the two widths) and adds ``-vdw`` to the name after ``-vdsb`` and ``-vdpw``.  The record
gains ``wait`` (None where the pass did not run; else ``evaluated``, ``now``,
``waited``, ``now_mean``, ``wait_mean``, the widths, ``draws_cap``, ``draws``,
``worlds_accepted``, ``worlds_completed``,
``same_outcome_worlds``, ``now_still_legal_worlds``, ``wait_end_declares``,
``end_choices_scored``, ``leaf_first_trick_fallbacks``, the fallback pair,
``seconds``); ``played`` and ``changed`` are the final decision.  Off, it is
absent from the payload, the record and the instance state, so every existing
name and every decision are unchanged.

Optional heuristic declaration variant with NO model call (the same
diagnostic), OFF BY DEFAULT: ``SHENGJI_PV_DECLARE_ASAP_FIRST=1`` -- in a round
with no fixed banker, at EVERY declare chance where the seat has an option,
the strongest option by the engine's own declaration strength
(`Round._declaration_strength`: single 1 < pair 2 < small-joker pair 3 <
big-joker pair 4, the order `Round.declare` enforces for an overcall) is
declared at once; equal strengths (singles or pairs of the trump rank in
different suits) go to the suit the hand holds most cards of, then engine
option order.  `Round.declare_options` lists only declarations STRICTLY
stronger than the current one whoever made it, so the seat overcalls itself
(its pair after its single) and other seats alike, and never re-declares what
it already holds.  No heuristic bar, no grace-window distinction.  In a round
with a fixed banker the decision IS the heuristic's.  EXCLUSIVE with
``SHENGJI_PV_VALUE_DECLARE`` (both on refuses: one declare policy at a time).
Record (``last_declare_record``, schema ``pv-declare-asap-decision-v1``, set on
every call with the flag on, None where it does not declare; carried by the
screen like the value-declare records): ``cards_dealt``, ``options`` (count),
``chosen``, ``strength``, ``overcall`` (a declaration stood), ``overcall_self``.
``0`` or ``1`` only; on, it enters the recipe digest and adds ``-asap`` to the
name in the declare slot (after ``-vdef``; the two policies never both
appear).  Off, it is absent from the payload, so every existing name and every
decision are unchanged.  Declare-rule token order: ``vd``, ``vdef``, ``vdsb``, ``vdpw``,
``vdw``, ``asap``.

Optional value-leaf rule (Jerry 2026-10-11: "where we use heuristics, it may be
better to use the model"), OFF BY DEFAULT: ``SHENGJI_PV_LEAF_POLICY_FIRST_TRICK=1``
-- in BOTH value leaves of this bot, the bury scoring of `PVSearchBuryBot`'s
hybrid/value arms (`cwv_bury.score_bury_candidates`) and the value declaration's
outcome position (`value_declare.declare_outcome_position`), the first trick
the frozen encoder needs before the value head can score the position is played
by the POLICY HEAD's argmax over each seat's COMPLETE legal set (the same
package's prior and the admission's additive score, one cheap call per seat and
world, no value call, no search; the argmax is computed from the legal set's
structure, not by enumerating it: `leaf_first_trick.PolicyFirstTrick`) instead
of the heuristic's play.  A seat whose policy call fails or ranks nothing falls
back to the heuristic play and is counted.  The calls run inside the stages'
existing budget checks (the bury's ``check_budget``, the declare's
`OptionalStage` guard), before every predictor batch, so the bury's 2 s and the
declare's budget bound them exactly as before and an expiry falls back to the
stage's incumbent (the heuristic bury, the heuristic declaration).  Measured on
release 44's package (smv3out-491ee4bf, 20 DEV bury roots / 20 seeded deals,
compiled engine, one thread, Mini): bury 0.11 s -> 0.59 s mean (max 0.94 s),
value declare 0.026 s -> 0.11 s mean (max 0.22 s).  ``0`` or ``1`` only; it
REQUIRES a leaf it changes --
``value_declare`` or a hybrid/value bury arm (refused otherwise: a name token
for a rule with no effect would be a lie); on, it enters the recipe digest
(with ``value_declare_model`` naming the policy first trick when the value
declaration is on) and adds ``-lpft`` to the name as the last rule token, after
the declare tokens (``vd``, ``vdef``, ``asap``).  Records: the bury record
(``cwv-bury-policy-v1`` and the fallback record) and the value-declare record
gain ``leaf_first_trick`` (``"heuristic"`` / ``"policy"``) and
``leaf_first_trick_fallbacks``.  Off, it is absent from the payload and the
leaves are untouched, so every existing name (release 44:
``pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-6c1fb26b80e6``)
and every decision are unchanged.  Rule token order:
div, fs, rc, rcec, whl, whd, bw, bwc, tb, ak16, wla, la, lp, dts, sjg, aw, awl, dtr, vd,
vdef, vdsb, vdpw, vdw, asap, lpft.

Optional wide value-only bury chooser (#707 S15), OFF BY DEFAULT:
``SHENGJI_PV_BURY_WIDE_VALUE=1`` (`bury_wide_value`; a BURY setting of
`PVSearchBuryBot`, so it needs a model bury arm, hybrid or value, and is refused
on heuristic/mc) replaces the arm's chooser with `bury_wide_value`: the
structured ballot is widened with the heuristic incumbent's single-card swaps
(deterministic order, deduplicated, the literal incumbent at index 0, the set
capped at ``SHENGJI_PV_BURY_WIDE_K``, default 32, refused without the flag), the
value head's mean over the arm's ``model_worlds`` worlds -- the same leaf as the
hybrid's value pass, the policy head's first trick under ``lpft`` -- picks the
argmax, and NO MC rollout stage runs.  The bury budget (2 s) bounds it through
the same ``check_budget`` at every expensive boundary and an expiry or error
falls back to the heuristic incumbent with today's fallback record.  The record
is ``cwv-bury-policy-v1`` plus ``wide_value`` (``candidates``, ``worlds``,
``chosen_index``, ``chosen_is_incumbent``, ``seconds``, the enumeration counts).
On, it enters the ``cwv-bury-recipe-v1`` identity (``wide_value``: the chooser
and ``k``) and the bury segment of the name gains ``-bwv`` after the arm
(``...-bury-hybrid-bwv-<12 hex>``); the play digest ``-r<recipe8>`` is untouched.
Off, it is absent from the identity, the bot's instance state and every record,
so every existing name and every decision are unchanged.  ``SHENGJI_PV_BURY_WIDE_K``
is an int in [2, 128].  With the chooser on, ``SHENGJI_PV_BURY_WIDE_SWAPS=2``
(`bury_wide_swaps`; ``1`` or ``2``, default 1, refused without the flag) fills the
slots after the ballot from the merged single- and two-card swap stream of the
incumbent (`bury_wide_value.ranked_swaps`: the two kinds interleaved by the sum of
their discard-preference ranks); the identity's ``wide_value`` gains ``swaps: 2``,
the bury token becomes ``-bwv2`` and the record's ``wide_value`` gains ``swaps``
and ``two_swap_count``.  ``swaps=1`` leaves every name, identity, record and
decision of the chooser exactly as without the setting.

Its optional second stage (#707 S15), OFF BY DEFAULT: ``SHENGJI_PV_BURY_TWO_STAGE=1``
(`bury_two_stage`; ``0`` or ``1``, refused without ``SHENGJI_PV_BURY_WIDE_VALUE=1``)
keeps the chooser's value argmax as stage 1 and re-scores the value top
``_BURY_TWO_STAGE_TOP`` (default 4) on ``_BURY_TWO_STAGE_WORLDS`` (32) fresh worlds
common to every candidate, each position played ``_BURY_TWO_STAGE_TRICKS`` (2) whole
tricks by the policy head before the value head scores it (an ended round: its
outcome); the stage-1 argmax stays unless the best stage-2 mean beats its own
stage-2 mean by more than ``_BURY_TWO_STAGE_MARGIN`` (0.0) and by more than
``_BURY_TWO_STAGE_Z`` (1.0) paired standard errors.  The stage has its own deadline,
``min(_BURY_TWO_STAGE_SECONDS (1.0) after it starts, the bury budget less 0.25 s)``, and
on an expiry or an error keeps the stage-1 argmax (never the heuristic fallback).
On, the identity's ``wide_value`` gains ``two_stage`` (the stage and its six
parameters), the bury token gains ``-bts`` after ``-bwv``/``-bwv2``
(``...-bury-hybrid-bwv-bts-<12 hex>``) and the record ``two_stage``.  Off, it is
absent from the identity, the bot's instance state and every record.  The value
declaration's served-bury world model (``vdsb``) keeps its own reduced stage-1
chooser either way.

Its optional kitty charge, OFF BY DEFAULT: ``SHENGJI_PV_BURY_KITTY_CHARGE=1``
(`bury_kitty_charge`; ``0`` or ``1``, refused without ``SHENGJI_PV_BURY_WIDE_VALUE=1``
and with ``SHENGJI_PV_BURY_TWO_STAGE=1`` or ``SHENGJI_PV_VALUE_DECLARE_SERVED_BURY=1``,
whose choices would not see it) takes the chooser's argmax over the value means less
each candidate kitty's expected bonus, ``total_points(kitty) x 0.38 x 3.0 / 40`` signed
levels (the attackers' last-trick rate, the mean multiplier when they take it, and the
level bracket width; constants from release-46 self-play).  On, the identity's
``wide_value`` gains ``kitty_charge`` (the three factors), the bury token gains ``-bkc``
after ``-bwv``/``-bwv2`` (``...-bury-hybrid-bwv-bkc-<12 hex>``) and the record
``kitty_charge``.  Off, it is absent from the identity, the bot's instance state and
every record.

DIAGNOSTIC ONLY, never served (#707 S16, the perfect-information ceiling), OFF
BY DEFAULT: ``SHENGJI_PV_ORACLE_WORLDS=1`` (token ``orc``, the last rule token
after ``lpft``; enters the recipe digest) replaces the W sampled completions of
the hidden hands with ONE world, the TRUE deal (the other three hands as dealt
and the kitty), for every PLAY decision: `_worlds` returns exactly that world,
``attempts`` 1, the sampler's RNG untouched, and the same search (admission,
value leaves, selection, the doomed-throw rules, the tree) runs over it.  Only
the play decisions are covered: the value declaration and the bury leaves draw
through their own samplers (`value_declare.sample_declare_world`,
`cwv_bury`) and are unchanged.  One world is sufficient: every consumer
reduces with ``sums / len(worlds)``, the tree visits ``min(len(worlds), ..)``
and ``adaptive_worlds`` needs two worlds to trigger, so the two adaptive rules
are refused with the oracle (they could never act).  A screen of this arm
against release 44 bounds how much of the remaining strength gap is
information (belief) rather than evaluation.

Privacy: the true hands reach the bot ONLY through the screen harness's hook
(`PVSearchBot.bind_oracle_deal`, installed by `cwv_shortlist_screen.make_side`
from `cwv_shortlist_screen.oracle_true_deal`); the bot itself never reads
another seat's hand off a `Round`.  With the rule on and no hook bound the
bot REFUSES (`OracleWorldsError`) -- before the serving fallback, which never
absorbs an oracle error, so no decision silently degrades to the heuristic.
Serving refuses it: `make_pv_search_bot` and the registry factory raise
without the harness's ``oracle_deal`` (the game server's `make_bot(name)`
passes none), `api.server` refuses the environment flag at import, and the
production package test (`SHENGJI_REQUIRE_PV_PACKAGE=1`) runs without it.
Off, the key is absent from the payload and `_worlds` is exactly production's
draw.  Rule token order with it: ..., vdef, asap, lpft, orc.

Its two SOFT variants (#707 S17 step 3; `pv_soft_oracle`), DIAGNOSTIC ONLY
under exactly the same hook, refusals and fail-closed contract, OFF BY
DEFAULT, each exclusive with ``orc``, with each other and with the adaptive
rules: ``SHENGJI_PV_ORACLE_MIX_K=<k>`` (``oracle_mix_k``, token ``orcm<k>``
right after the rule tokens) makes ``k`` of the W play worlds the true deal
and draws the other ``W - k`` through production's sampler;
``SHENGJI_PV_ORACLE_PIN_Q=<q>`` (``oracle_pin_q``, token ``orcq<100 q>``)
draws each of the W worlds through production's count search and dealer with
a seeded fraction ``q`` of the hidden copies pinned to their true holders,
checks it against every constraint, and falls back to production's draw (and
counts it) when no valid fill is found.  Both enter the recipe digest and add
scalar ``oracle_*`` fields to the decision record (`_soft_oracle_record`).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections import Counter
from dataclasses import asdict, dataclass

import numpy as np

from ..ai.cwv_policy import file_sha256, sample_worlds, shared_evaluator
from ..engine.cards import card_suit, is_joker
from ..ai.heuristic import HeuristicBot
from ..ai.memory import Memory
from ..ai.refusal import RefusalLedger, sample_worlds_refusal_aware
from ..ai.history_legality import draw_constraints, sample_worlds_history_legal
from ..ai.belief_numpy import (PREP_SECONDS as BELIEF_PREP_SECONDS, PROPOSAL as BELIEF_PROPOSAL,
                               PROPOSAL_CAPACITY as BELIEF_PROPOSAL_CAPACITY,
                               SCHEMA as BELIEF_SCHEMA)
from ..harvest.legal import enumerate_legal
from .cwv_prior_admission import (CWVPriorAdmissionBot, load_prior_checked,
                                  prior_encoder_version, root_clone)
from .policy_value_search import (ADAPTIVE_K_DEFAULTS, ADMISSION_DEFAULTS, FORCED_EXTRA_SLOTS,
                                  DOOMED_THROW_DEFAULTS, DOOMED_THROW_RESELECT_DEFAULTS,
                                  DOOMED_THROW_RESELECT_EXACT_GUARD_DEFAULTS,
                                  LEAF_GREEDY_DEFAULTS, LEAF_GREEDY_REPLIES,
                                  LEAD_ANCHOR_DEFAULTS,
                                  LEAD_TIEBREAK_DEFAULTS, SMALL_JOKER_GUARD_DEFAULTS,
                                  TIEBREAK_DEFAULTS, PolicyValueBot, leading)
from .optional_stage import OptionalStage
from . import value_declare as value_declare_model
from .cwv_bury_policy import (_ARMS as BURY_ARMS, _MODEL_ARMS as BURY_MODEL_ARMS,
                              ARM_ALIASES as BURY_ARM_ALIASES,
                              BuryPolicyError, CWVBuryConfig,
                              CWVBuryMixin, _serving_budget as _bury_budget)
from .leaf_first_trick import PolicyFirstTrick
from .exact_lead_policy_first import LIMITS as EXACT_LEAD_POLICY_LIMITS
from .bury_two_stage import (TOKEN as BURY_TWO_STAGE_TOKEN, TwoStageConfig as BuryTwoStageConfig)
from .bury_kitty_charge import (TOKEN as BURY_KITTY_CHARGE_TOKEN,
                                identity as bury_kitty_charge_identity)
from .bury_wide_value import (WIDE_K_DEFAULT as BURY_WIDE_K_DEFAULT, CHOOSER as BURY_WIDE_CHOOSER,
                              WIDE_K_MAX as BURY_WIDE_K_MAX,
                              WIDE_SWAPS_DEFAULT as BURY_WIDE_SWAPS_DEFAULT,
                              TOKEN as BURY_WIDE_TOKEN, TOKEN_TWO_SWAPS as BURY_WIDE_TOKEN_TWO_SWAPS,
                              check_wide_k, check_wide_swaps, decide_wide_value_bury)
from . import declare_served_bury
from . import declare_pass_worlds
from . import declare_wait
from . import pv_soft_oracle as soft_oracle
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
#: and the history-legal world test (`ai.history_legality`, board row S27)
SAMPLER_RULES = {"REFUSAL_CONSTRAINTS": "refusal_constraints",
                 "REFUSAL_EVENT_COMPLETE": "refusal_event_complete",
                 "WORLD_HISTORY_LEGAL": "world_history_legal",
                 "WORLD_HISTORY_DRAW": "world_history_draw",
                 "BELIEF_WORLDS": "belief_worlds",
                 "BELIEF_CAPACITY": "belief_capacity"}
SAMPLER_DEFAULTS = dict(refusal_constraints=False, refusal_event_complete=False,
                        world_history_legal=False, world_history_draw=False, belief_worlds=False,
                        belief_capacity=False)
#: name tokens, in name order, for the rules that are on
SAMPLER_TOKENS = (("refusal_constraints", "rc"), ("refusal_event_complete", "rcec"),
                  ("world_history_legal", "whl"), ("world_history_draw", "whd"),
                  ("belief_worlds", "bw"), ("belief_capacity", "bwc"))
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
#: its exact-stage guard (`policy_value_search`; requires it and ``exact_lead_endgame``)
DOOMED_THROW_RESELECT_EXACT_GUARD_RULE = {
    "DOOMED_THROW_RESELECT_EXACT_GUARD": "doomed_throw_reselect_exact_guard"}
#: the guard's recipe identity: on an exact-stage selection the re-select moves
#: only to a candidate whose exact mean is not below the selected one's
DOOMED_THROW_RESELECT_EXACT_RULE = "reselect-only-to-exact-mean-not-below-selected"
_DOOMED_THROW_RESELECT_EXACT_GUARD_REQUIRES = (
    "doomed_throw_reselect_exact_guard requires doomed_throw_reselect and exact_lead_endgame "
    "(SHENGJI_PV_DOOMED_THROW_RESELECT_EXACT_GUARD=1 needs SHENGJI_PV_DOOMED_THROW_RESELECT=1 "
    "and SHENGJI_PV_EXACT_LEAD_ENDGAME=1)")
#: the optional value-leaf finisher (`policy_value_search`; refused with the tree or
#: the adaptive worlds rule)
LEAF_GREEDY_RULE = {"LEAF_GREEDY_FINISH": "leaf_greedy_finish"}
#: its recipe identity: the scored leaf's current trick is finished by the greedy
#: reply ply with the policy's top-R follows plus the heuristic's
LEAF_GREEDY_FINISH_RULE = f"value-leaf-trick-greedy-r{LEAF_GREEDY_REPLIES}"
_LEAF_GREEDY_EXCLUSIVE = (
    "leaf_greedy_finish does not combine with the tree or adaptive_worlds "
    "(SHENGJI_PV_LEAF_GREEDY_FINISH=1 with SHENGJI_PV_TREE_SIMS, SHENGJI_PV_ADAPTIVE_WORLDS "
    "or SHENGJI_PV_ADAPTIVE_WORLDS_LEADS)")
#: its exact-stage yield (requires it and an exact stage): the plain leaf on a
#: decision an exact stage is eligible for
LEAF_GREEDY_EXACT_SKIP_RULE = {"LEAF_GREEDY_FINISH_EXACT_SKIP": "leaf_greedy_finish_exact_skip"}
LEAF_GREEDY_EXACT_SKIP_DEFAULTS = dict(leaf_greedy_finish_exact_skip=False)
#: its recipe identity
LEAF_GREEDY_EXACT_SKIP_RULE_ID = "heuristic-leaf-on-exact-eligible-decisions"
#: ``SHENGJI_PV_LEAF_GREEDY_DEADLINE=<seconds>`` (``leaf_greedy_deadline_ms``,
#: token ``lgfd<ms>`` after ``lgf``/``lgfx``): 0 is off
LEAF_GREEDY_DEADLINE_ENV = "LEAF_GREEDY_DEADLINE"
LEAF_GREEDY_DEADLINE_TOKEN = "lgfd"
LEAF_GREEDY_DEADLINE_RULE_ID = "heuristic-leaves-once-the-decision-passes-the-deadline-in-the-finish"
#: the deadline's range in ms
LEAF_GREEDY_DEADLINE_MS_RANGE = (1, 60_000)
#: ``SHENGJI_PV_LEAF_GREEDY_TOP=<m>`` (``leaf_greedy_top``, token ``lgft<m>``
#: after the greedy leaf's tokens): 0 is off
LEAF_GREEDY_TOP_ENV = "LEAF_GREEDY_TOP"
LEAF_GREEDY_TOP_TOKEN = "lgft"
LEAF_GREEDY_TOP_RULE_ID = "lgf-on-plain-leaf-top-m-pruned-ranked-by-plain-mean-below-kept"
LEAF_GREEDY_TOP_RANGE = (1, 64)
#: subtracted from a pruned candidate's plain mean: the head's means are signed
#: levels a few units wide, so every pruned candidate ranks below every kept one
LEAF_GREEDY_TOP_OFFSET = 1000.0
_LEAF_GREEDY_TOP_REQUIRES = (
    "leaf_greedy_top requires leaf_greedy_finish "
    "(SHENGJI_PV_LEAF_GREEDY_TOP needs SHENGJI_PV_LEAF_GREEDY_FINISH=1)")
_LEAF_GREEDY_DEADLINE_REQUIRES = (
    "leaf_greedy_deadline_ms requires leaf_greedy_finish "
    "(SHENGJI_PV_LEAF_GREEDY_DEADLINE needs SHENGJI_PV_LEAF_GREEDY_FINISH=1)")
_LEAF_GREEDY_EXACT_SKIP_REQUIRES = (
    "leaf_greedy_finish_exact_skip requires leaf_greedy_finish and an exact stage "
    "(SHENGJI_PV_LEAF_GREEDY_FINISH_EXACT_SKIP=1 needs SHENGJI_PV_LEAF_GREEDY_FINISH=1 and "
    "SHENGJI_PV_EXACT_LEAD_ENDGAME=1 or SHENGJI_PV_EXACT_FOLLOW=1)")
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
#: ``SHENGJI_PV_WIDE_LEAD_K=<k>`` (``wide_lead_k``; needs ``wide_lead_admission``)
WIDE_LEAD_K_ENV = "WIDE_LEAD_K"
WIDE_LEAD_K_RANGE = (9, 64)
#: ``SHENGJI_PV_LEAD_CONFIRM=<k>`` (``lead_confirm``, token ``lcc<k>``): extra lead
#: candidates (the policy's next ``k - K`` beyond the served ballot) may replace the
#: served lead only after a fresh world draw confirms one (`PVSearchBot` docstring); 0 is off
LEAD_CONFIRM_ENV = "LEAD_CONFIRM"
LEAD_CONFIRM_TOKEN = "lcc"
LEAD_CONFIRM_RULE_ID = ("policy-pool-beyond-ballot-screened-on-base-world-prefix-"
                        "replaces-served-lead-only-if-paired-delta-on-fresh-worlds-exceeds-z-se")
LEAD_CONFIRM_K_RANGE = (9, 64)
#: its parameters, digested with the rule: the base-world prefix the pool is
#: screened on, the challengers taken to confirmation, the fresh W-world draws
#: they are confirmed on, the paired z and value margin a challenger must clear,
#: and the start / soft shares of the serving budget
LEAD_CONFIRM_PARAMS = dict(screen_worlds=32, challengers=2, rounds=2, z=1.0, margin=0.0,
                           start_fraction=0.4, soft_fraction=0.8)
#: the per-decision rule records the base finalization set; an abandon restores them
LEAD_CONFIRM_RULE_STATE = ("_tiebreak", "_lead_tiebreak", "_doomed_throw", "_last_sampling")
_LEAD_CONFIRM_EXCLUSIVE = ("lead_confirm does not combine with the tree or adaptive worlds "
                           "(SHENGJI_PV_LEAD_CONFIRM with SHENGJI_PV_TREE_SIMS, "
                           "SHENGJI_PV_ADAPTIVE_WORLDS or SHENGJI_PV_ADAPTIVE_WORLDS_LEADS)")
FINISH_LEAD_RULE = {"FINISH_LEAD_ADMISSION": "finish_lead_admission"}
EXACT_LEAD_RULE = {"EXACT_LEAD_ENDGAME": "exact_lead_endgame"}
EXACT_FOLLOW_RULE = {"EXACT_FOLLOW": "exact_follow"}
#: its two optional variants (module docstring); each requires ``exact_lead_endgame``
EXACT_LEAD_VARIANT_RULES = {"EXACT_LEAD_TIE_BASELINE": "exact_lead_tie_baseline",
                            "EXACT_LEAD_POLICY_FIRST": "exact_lead_policy_first"}
#: the tie rule's recipe identity: the exact pass replaces the baseline lead
#: only on a strictly higher exact mean (exact float comparison)
EXACT_LEAD_TIE_RULE = "replace-only-if-selected-exact-mean-gt-baseline-exact-mean"
_EXACT_LEAD_VARIANT_REQUIRES = ("exact_lead_tie_baseline / exact_lead_policy_first / "
                                "exact_deep_cards require exact_lead_endgame "
                                "(SHENGJI_PV_EXACT_LEAD_TIE_BASELINE=1, "
                                "SHENGJI_PV_EXACT_LEAD_POLICY_FIRST=1 or "
                                "SHENGJI_PV_EXACT_DEEP_CARDS needs "
                                "SHENGJI_PV_EXACT_LEAD_ENDGAME=1)")
#: the deeper exact rule's parameter (module docstring): env suffix -> keyword;
#: 0 is off and kept out of the payload
EXACT_DEEP_PARAM = {"EXACT_DEEP_CARDS": "exact_deep_cards"}
EXACT_DEEP_CARDS_RANGE = (4, 8)
EXACT_DEEP_LIMITS = dict(max_nodes=50_000_000, solver="level-cuts-relative-tt-ordered")
EXACT_LEAD_LIMITS = dict(max_hand_cards=4, max_nodes=10000, max_seconds=2.25,
                         start_fraction=0.5, soft_fraction=0.8)
#: DEV caps for an exact-lead ceiling measurement (module docstring): env suffix
#: -> keyword.  Each defaults to the constant above and is ABSENT from the name
#: and payload at that value, so a served recipe keeps its identity; any other
#: value replaces the constant in the digested limits and adds a name token.
EXACT_LEAD_CAP_PARAMS = {"EXACT_LEAD_MAX_SECONDS": "exact_lead_max_seconds",
                         "EXACT_DEEP_MAX_NODES": "exact_deep_max_nodes"}
EXACT_LEAD_CAP_DEFAULTS = dict(exact_lead_max_seconds=EXACT_LEAD_LIMITS["max_seconds"],
                               exact_deep_max_nodes=EXACT_DEEP_LIMITS["max_nodes"])
#: the accepted ranges: a stage deadline of at least a millisecond and at most a
#: day (its name token is ``els<ms>``), and a per-world node cap up to 10**12
EXACT_LEAD_MAX_SECONDS_RANGE = (0.001, 86400.0)
EXACT_DEEP_MAX_NODES_RANGE = (1, 10**12)
FINISH_LEAD_MAX_CARDS = 8
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
#: the optional declaration rule (`PVSearchBot.decide_declare`, `value_declare`)
VALUE_DECLARE_RULE = {"VALUE_DECLARE": "value_declare"}
#: its parameters: sampled deals per evaluation, and the value margin (expected
#: signed levels, the head's units) the best candidate must beat the heuristic's by
VALUE_DECLARE_DEFAULTS = dict(value_declare=False, value_declare_worlds=64,
                              value_declare_margin=0.0)
VALUE_DECLARE_PARAMS = {"VALUE_DECLARE_WORLDS": "value_declare_worlds",
                        "VALUE_DECLARE_MARGIN": "value_declare_margin"}
#: the record a value-declare decision leaves in ``last_declare_record``
VALUE_DECLARE_RECORD_SCHEMA = "pv-value-declare-decision-v1"
#: its first-round gate widening (requires ``value_declare``; module docstring)
VALUE_DECLARE_EVERY_FIRST_RULE = {"VALUE_DECLARE_EVERY_FIRST": "value_declare_every_first"}
VALUE_DECLARE_EVERY_FIRST_DEFAULTS = dict(value_declare_every_first=False)
#: the gate names the value-declare record carries (why a chance was admitted)
VALUE_DECLARE_GATES = ("heuristic", "final", "every_first")
#: the served bury inside the value declaration's worlds (requires ``value_declare``
#: and the wide value-only bury chooser; module docstring, `declare_served_bury`)
VALUE_DECLARE_SERVED_BURY_RULE = {"VALUE_DECLARE_SERVED_BURY": "value_declare_served_bury"}
VALUE_DECLARE_SERVED_BURY_DEFAULTS = dict(value_declare_served_bury=False)
#: its pass-conditioned declare worlds (requires ``value_declare``; module
#: docstring, `declare_pass_worlds`)
VALUE_DECLARE_PASS_WORLDS_RULE = {"VALUE_DECLARE_PASS_WORLDS": "value_declare_pass_worlds"}
VALUE_DECLARE_PASS_WORLDS_DEFAULTS = dict(value_declare_pass_worlds=False)
#: the wait option of the value declaration (requires ``value_declare``; module
#: docstring, `declare_wait`)
VALUE_DECLARE_WAIT_RULE = {"VALUE_DECLARE_WAIT": "value_declare_wait"}
VALUE_DECLARE_WAIT_DEFAULTS = dict(value_declare_wait=False)
#: the model-free first-round declaration variant (exclusive with ``value_declare``)
DECLARE_ASAP_RULE = {"DECLARE_ASAP_FIRST": "declare_asap_first"}
DECLARE_ASAP_DEFAULTS = dict(declare_asap_first=False)
#: the record a declare-asap declaration leaves in ``last_declare_record``
DECLARE_ASAP_RECORD_SCHEMA = "pv-declare-asap-decision-v1"
#: the optional value-leaf rule (module docstring; `leaf_first_trick`): the
#: policy head plays the leaf's first trick in the bury scoring and the value
#: declaration; requires one of those leaves
LEAF_POLICY_RULE = {"LEAF_POLICY_FIRST_TRICK": "leaf_policy_first_trick"}
LEAF_POLICY_DEFAULTS = dict(leaf_policy_first_trick=False)
#: the record values of ``leaf_first_trick`` (who played the leaf's first trick)
LEAF_FIRST_TRICK_PLAYERS = ("heuristic", "policy")
#: the optional wide value-only bury chooser of `PVSearchBuryBot` (module
#: docstring; `bury_wide_value`): env suffix -> keyword, and the defaults.  A
#: BURY setting, not a play-recipe rule: it enters the ``cwv-bury-recipe-v1``
#: identity and the bury segment of the name (``-bury-<arm>-bwv-<12 hex>``),
#: never the play digest ``-r<recipe8>``
BURY_WIDE_VALUE_FLAG = {"BURY_WIDE_VALUE": "bury_wide_value"}
BURY_WIDE_VALUE_PARAM = {"BURY_WIDE_K": "bury_wide_k"}
BURY_WIDE_VALUE_DEFAULTS = dict(bury_wide_value=False, bury_wide_k=BURY_WIDE_K_DEFAULT)
_BURY_WIDE_VALUE_NO_EFFECT = ("bury_wide_value needs a model bury arm, hybrid or value "
                              "(SHENGJI_PV_BURY_WIDE_VALUE=1 with SHENGJI_PV_BURY_ARM=heuristic|mc)")
_BURY_WIDE_K_REQUIRES = ("bury_wide_k needs bury_wide_value "
                         "(SHENGJI_PV_BURY_WIDE_K needs SHENGJI_PV_BURY_WIDE_VALUE=1)")
#: its swap depth (`bury_wide_value.ranked_swaps`): 1 (the default) or 2; kept
#: out of ``BURY_WIDE_VALUE_PARAM``/``_DEFAULTS`` so those (and every flag-off
#: construction) are exactly what they were
BURY_WIDE_SWAPS_PARAM = {"BURY_WIDE_SWAPS": "bury_wide_swaps"}
_BURY_WIDE_SWAPS_REQUIRES = ("bury_wide_swaps needs bury_wide_value "
                             "(SHENGJI_PV_BURY_WIDE_SWAPS needs SHENGJI_PV_BURY_WIDE_VALUE=1)")
#: the optional second stage of the wide chooser (module docstring;
#: `bury_two_stage`): the flag, and its parameters (env suffix ->
#: `bury_two_stage.TwoStageConfig` field), each refused without the flag; kept
#: out of every flag-off construction (the bot's keyword is a config or None)
BURY_TWO_STAGE_FLAG = {"BURY_TWO_STAGE": "bury_two_stage"}
BURY_TWO_STAGE_PARAMS = {"BURY_TWO_STAGE_TOP": "top", "BURY_TWO_STAGE_WORLDS": "worlds",
                         "BURY_TWO_STAGE_TRICKS": "tricks", "BURY_TWO_STAGE_MARGIN": "margin",
                         "BURY_TWO_STAGE_Z": "z", "BURY_TWO_STAGE_SECONDS": "seconds"}
_BURY_TWO_STAGE_REQUIRES = ("bury_two_stage needs bury_wide_value "
                            "(SHENGJI_PV_BURY_TWO_STAGE=1 needs SHENGJI_PV_BURY_WIDE_VALUE=1)")
#: the optional kitty charge of the wide chooser (module docstring;
#: `bury_kitty_charge`): a 0/1 bury setting, kept out of every flag-off
#: construction (the bot's keyword is passed only when on)
BURY_KITTY_CHARGE_FLAG = {"BURY_KITTY_CHARGE": "bury_kitty_charge"}
_BURY_KITTY_CHARGE_REQUIRES = ("bury_kitty_charge needs bury_wide_value "
                               "(SHENGJI_PV_BURY_KITTY_CHARGE=1 needs SHENGJI_PV_BURY_WIDE_VALUE=1)")
_BURY_KITTY_CHARGE_EXCLUSIVE = ("bury_kitty_charge is exclusive with bury_two_stage and "
                                "value_declare_served_bury, whose choices would not see the "
                                "charge (SHENGJI_PV_BURY_KITTY_CHARGE=1 with "
                                "SHENGJI_PV_BURY_TWO_STAGE=1 or SHENGJI_PV_VALUE_DECLARE_SERVED_BURY=1)")
#: the DIAGNOSTIC perfect-information rule (module docstring; #707 S16): the
#: play worlds are the one true deal, supplied by the screen harness's hook;
#: never served
ORACLE_WORLDS_RULE = {"ORACLE_WORLDS": "oracle_worlds"}
ORACLE_WORLDS_DEFAULTS = dict(oracle_worlds=False)
#: its SOFT variants (module docstring; #707 S17 step 3): env suffix -> recipe
#: key, and the defaults (0 = off).  Parameters, not 0/1 flags, so they sit
#: outside ``RULE_FLAGS``; their name token follows the rule tokens
ORACLE_SOFT_PARAMS = {"ORACLE_MIX_K": "oracle_mix_k", "ORACLE_PIN_Q": "oracle_pin_q"}
ORACLE_SOFT_DEFAULTS = dict(oracle_mix_k=0, oracle_pin_q=0.0)
#: its cumulative construction-work counters (`PVSearchBot.soft_oracle_counts`;
#: the screen reports them as ``soft_oracle_<name>``).  Production sampler calls
#: keep their own counters; these never relabel them:
#: ``constructions`` started and ``constructions_complete``; k-mix
#: ``true_worlds`` placed and ``production_worlds`` requested from production's
#: draw; q-pin ``pin_fills`` attempted, of which ``pin_fill_failed`` (no fill)
#: and ``pin_rejections`` (a constraint broken), ``pin_worlds`` accepted,
#: ``pinned_copies`` in them, and ``pin_fallback_worlds`` handed to production
SOFT_ORACLE_COUNTERS = ("constructions", "constructions_complete", "true_worlds",
                        "production_worlds", "pin_fills", "pin_fill_failed", "pin_rejections",
                        "pin_worlds", "pinned_copies", "pin_fallback_worlds")
#: every optional 0/1 rule flag, env suffix -> recipe key, and every name token in
#: name order (admission rules, the sampler rules, selection, width -- the
#: multi-card-lead width and the exclusive all-leads width --, anchor, lead
#: selection, played action, small-joker guard, adaptive worlds, its leads-only
#: scope, the doomed-throw re-select, its exact-stage guard, the value
#: declaration, its first-round gate, the served bury in its worlds, its
#: pass-conditioned worlds, its wait option, the model-free first-round
#: declaration, the policy-played value leaf, the greedy-finished value leaf,
#: its exact-stage yield, the diagnostic oracle worlds):
#: div, fs, rc, rcec, whl, whd, bw, bwc, tb, fla, ak16, wla, la, lp, dts, sjg, aw, awl, dtr, dtrx,
#: vd, vdef, vdsb, vdpw, vdw, asap, lpft, lgf, lgfx, orc
RULE_FLAGS = {**ADMISSION_RULES, **SAMPLER_RULES, **TIEBREAK_RULE, **ADAPTIVE_K_RULE,
              **LEAD_ANCHOR_RULE, **LEAD_TIEBREAK_RULE, **DOOMED_THROW_RULE,
              **SMALL_JOKER_GUARD_RULE, **ADAPTIVE_WORLDS_RULE, **WIDE_LEAD_RULE,
              **DOOMED_THROW_RESELECT_RULE, **DOOMED_THROW_RESELECT_EXACT_GUARD_RULE,
              **VALUE_DECLARE_RULE,
              **VALUE_DECLARE_EVERY_FIRST_RULE, **VALUE_DECLARE_SERVED_BURY_RULE,
              **VALUE_DECLARE_PASS_WORLDS_RULE, **VALUE_DECLARE_WAIT_RULE,
              **DECLARE_ASAP_RULE, **LEAF_POLICY_RULE, **LEAF_GREEDY_RULE,
              **LEAF_GREEDY_EXACT_SKIP_RULE,
              **FINISH_LEAD_RULE, **ORACLE_WORLDS_RULE, **EXACT_LEAD_RULE,
              **EXACT_LEAD_VARIANT_RULES, **EXACT_FOLLOW_RULE}
RULES = RULE_FLAGS
RULE_TOKENS = ADMISSION_TOKENS + SAMPLER_TOKENS + (("tiebreak_points", "tb"),
                                                   ("finish_lead_admission", "fla"),
                                                   ("exact_lead_endgame", "ele"),
                                                   ("exact_lead_tie_baseline", "elt"),
                                                   ("exact_lead_policy_first", "elp"),
                                                   ADAPTIVE_K_TOKEN,
                                                   ("wide_lead_admission", "wla"),
                                                   ("lead_anchor", "la"),
                                                   ("lead_tiebreak_prior", "lp"),
                                                   ("doomed_throw_swap", "dts"),
                                                   ("small_joker_guard", "sjg"),
                                                   ("adaptive_worlds", "aw"),
                                                   ("adaptive_worlds_leads", "awl"),
                                                   ("doomed_throw_reselect", "dtr"),
                                                   ("doomed_throw_reselect_exact_guard", "dtrx"),
                                                   ("value_declare", "vd"),
                                                   ("value_declare_every_first", "vdef"),
                                                   ("value_declare_served_bury",
                                                    declare_served_bury.TOKEN),
                                                   ("value_declare_pass_worlds",
                                                    declare_pass_worlds.TOKEN),
                                                   ("value_declare_wait", declare_wait.TOKEN),
                                                   ("declare_asap_first", "asap"),
                                                   ("leaf_policy_first_trick", "lpft"),
                                                   ("leaf_greedy_finish", "lgf"),
                                                   ("leaf_greedy_finish_exact_skip", "lgfx"),
                                                   ("oracle_worlds", "orc"))
ENV_PREFIX = "SHENGJI_PV_"
_ORACLE_NOT_SERVED = ("oracle_worlds is a screen-harness diagnostic and is never served: "
                      "SHENGJI_PV_ORACLE_WORLDS=1 needs the harness's true-deal hook "
                      "(cwv_shortlist_screen passes oracle_deal=; the game server never does)")
_SOFT_ORACLE_NOT_SERVED = ("oracle_mix_k / oracle_pin_q are screen-harness diagnostics and are "
                           "never served: SHENGJI_PV_ORACLE_MIX_K / _ORACLE_PIN_Q need the "
                           "harness's true-deal hook (cwv_shortlist_screen passes oracle_deal=; "
                           "the game server never does)")
_ORACLE_HOOK_WITHOUT_RULE = ("oracle_deal is the oracle_worlds hook; this recipe has the rule "
                             "off (SHENGJI_PV_ORACLE_WORLDS, _ORACLE_MIX_K and _ORACLE_PIN_Q unset)")
_ORACLE_ADAPTIVE_EXCLUSIVE = ("oracle_worlds and the adaptive-worlds rules are exclusive: one "
                              "true world can never trigger them (SHENGJI_PV_ORACLE_WORLDS=1 "
                              "with SHENGJI_PV_ADAPTIVE_WORLDS=1 or _ADAPTIVE_WORLDS_LEADS=1)")
_SOFT_ORACLE_EXCLUSIVE = ("oracle_worlds, oracle_mix_k and oracle_pin_q are exclusive with each "
                          "other and with the adaptive-worlds rules (whose extra draws would "
                          "carry no truth)")


def _check_soft_oracle(config) -> tuple[int, float]:
    """``(oracle_mix_k, oracle_pin_q)`` of a config, validated: types, ranges
    (``1 <= k < worlds``; ``q`` a whole percentage in (0, 1)) and exclusivity."""
    try:
        k = soft_oracle.check_mix_k(config.oracle_mix_k, config.worlds)
        q = soft_oracle.check_pin_q(config.oracle_pin_q)
    except soft_oracle.SoftOracleConfigError as exc:
        raise PVSearchPolicyError(str(exc)) from None
    if (k or q) and (sum((bool(config.oracle_worlds), bool(k), bool(q))) > 1
                     or config.adaptive_worlds or config.adaptive_worlds_leads):
        raise PVSearchPolicyError(_SOFT_ORACLE_EXCLUSIVE)
    return k, q
_LEAF_POLICY_NO_EFFECT = ("leaf_policy_first_trick needs a value leaf it changes: value_declare "
                          "or a hybrid/value bury arm (SHENGJI_PV_LEAF_POLICY_FIRST_TRICK=1 "
                          "without SHENGJI_PV_VALUE_DECLARE=1 or SHENGJI_PV_BURY_ARM=hybrid|value)")
_VALUE_DECLARE_EVERY_FIRST_REQUIRES = ("value_declare_every_first requires value_declare "
                                       "(SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST=1 needs "
                                       "SHENGJI_PV_VALUE_DECLARE=1)")
_VALUE_DECLARE_SERVED_BURY_REQUIRES = ("value_declare_served_bury requires value_declare "
                                       "(SHENGJI_PV_VALUE_DECLARE_SERVED_BURY=1 needs "
                                       "SHENGJI_PV_VALUE_DECLARE=1)")
_VALUE_DECLARE_SERVED_BURY_NO_EFFECT = ("value_declare_served_bury needs the served wide "
                                        "value-only bury (SHENGJI_PV_VALUE_DECLARE_SERVED_BURY=1 "
                                        "needs SHENGJI_PV_BURY_ARM=hybrid|value and "
                                        "SHENGJI_PV_BURY_WIDE_VALUE=1)")
_VALUE_DECLARE_PASS_WORLDS_REQUIRES = ("value_declare_pass_worlds requires value_declare "
                                       "(SHENGJI_PV_VALUE_DECLARE_PASS_WORLDS=1 needs "
                                       "SHENGJI_PV_VALUE_DECLARE=1)")
_VALUE_DECLARE_WAIT_REQUIRES = ("value_declare_wait requires value_declare "
                                "(SHENGJI_PV_VALUE_DECLARE_WAIT=1 needs "
                                "SHENGJI_PV_VALUE_DECLARE=1)")
_DECLARE_ASAP_EXCLUSIVE = ("declare_asap_first and value_declare are exclusive "
                           "(SHENGJI_PV_DECLARE_ASAP_FIRST=1 with SHENGJI_PV_VALUE_DECLARE=1)")
_WIDE_LEAD_EXCLUSIVE = ("wide_lead_admission and adaptive_k are exclusive "
                        "(SHENGJI_PV_WIDE_LEAD_ADMISSION=1 with SHENGJI_PV_ADAPTIVE_K=1)")
_ADAPTIVE_WORLDS_EXCLUSIVE = ("adaptive_worlds and adaptive_worlds_leads are exclusive "
                              "(SHENGJI_PV_ADAPTIVE_WORLDS=1 with SHENGJI_PV_ADAPTIVE_WORLDS_LEADS=1)")
_HISTORY_LEGAL_ORACLE_EXCLUSIVE = ("world_history_legal and the oracle diagnostics are exclusive: "
                                   "the oracle worlds bypass the sampler the test applies to "
                                   "(SHENGJI_PV_WORLD_HISTORY_LEGAL=1 with SHENGJI_PV_ORACLE_WORLDS, "
                                   "_ORACLE_MIX_K or _ORACLE_PIN_Q)")
_BELIEF_REQUIRES = ("belief_worlds requires world_history_legal and world_history_draw: the "
                    "belief proposal plugs into the history-legal draw and honours its draw-time "
                    "constraints (SHENGJI_PV_BELIEF_WORLDS=1 needs SHENGJI_PV_WORLD_HISTORY_LEGAL=1 "
                    "and SHENGJI_PV_WORLD_HISTORY_DRAW=1)")
_BELIEF_CAPACITY_REQUIRES = ("belief_capacity requires belief_worlds: it is the belief proposal's "
                             "draw (SHENGJI_PV_BELIEF_CAPACITY=1 needs SHENGJI_PV_BELIEF_WORLDS=1)")
#: the belief proposal's log flag: ``0`` or ``1``, unset (or empty) is the default
BELIEF_LOG_ENV = "SHENGJI_PV_BELIEF_LOG"
BELIEF_LOG_DEFAULT = True


def belief_log_enabled(environ=None) -> bool:
    """``SHENGJI_PV_BELIEF_LOG`` as a bool; anything but ``0``/``1``/unset refuses."""
    env = os.environ if environ is None else environ
    raw = env.get(BELIEF_LOG_ENV)
    if raw in (None, ""):
        return BELIEF_LOG_DEFAULT
    if raw not in ("0", "1"):
        raise PVSearchPolicyError(f"{BELIEF_LOG_ENV} must be 0 or 1, not {raw!r}")
    return raw == "1"


#: the exact stages' world subset (module docstring): its env, name token and the
#: pinned selection and weighting it enters the payload with
EXACT_WORLD_SUBSET_ENV = "EXACT_WORLD_SUBSET"
EXACT_WORLD_SUBSET_TOKEN = "exs"
EXACT_WORLD_SUBSET_RULE = {"selection": "first-n-in-draw-order", "weights": "uniform",
                           "other_rules": "every-world"}
_EXACT_WORLD_SUBSET_REQUIRES = (
    "exact_world_subset narrower than worlds needs an exact stage "
    "(SHENGJI_PV_EXACT_WORLD_SUBSET below SHENGJI_PV_WORLDS needs "
    "SHENGJI_PV_EXACT_LEAD_ENDGAME=1 or SHENGJI_PV_EXACT_FOLLOW=1)")
#: the latency switches (module docstring): ``0`` or ``1``, unset (or empty) is off
LATENCY_SWITCH_ENV = {"encode_prefix_cache": "SHENGJI_PV_ENCODE_PREFIX_CACHE",
                      "single_candidate_fast": "SHENGJI_PV_SINGLE_CANDIDATE_FAST",
                      "leaf_greedy_stream": "SHENGJI_PV_LEAF_GREEDY_STREAM",
                      "encode_batch_fast": "SHENGJI_PV_ENCODE_BATCH_FAST",
                      "legal_native": "SHENGJI_PV_LEGAL_NATIVE",
                      "encode_native": "SHENGJI_PV_ENCODE_NATIVE",
                      "leaf_cache_release": "SHENGJI_PV_LEAF_CACHE_RELEASE",
                      "leaf_clone_fast": "SHENGJI_PV_LEAF_CLONE_FAST",
                      "leaf_trick_cache": "SHENGJI_PV_LEAF_TRICK_CACHE",
                      "world_fast": "SHENGJI_PV_WORLD_FAST"}


def latency_switches(environ=None) -> dict[str, bool]:
    """Each latency switch as a bool; anything but ``0``/``1``/unset refuses."""
    env = os.environ if environ is None else environ
    out = {}
    for attr, name in LATENCY_SWITCH_ENV.items():
        raw = env.get(name)
        if raw not in (None, "", "0", "1"):
            raise PVSearchPolicyError(f"{name} must be 0 or 1, not {raw!r}")
        out[attr] = raw == "1"
    return out


def _single_candidate_refusal(consumer):
    return PVSearchPolicyError(
        f"{consumer} reads every admitted candidate's value, and "
        f"{LATENCY_SWITCH_ENV['single_candidate_fast']}=1 leaves a one-candidate decision "
        "unpriced; unset it for this run")


def refuse_single_candidate_fast_env(consumer, environ=None) -> None:
    """Refuse, before any work, a numeric-value consumer started with the
    single-candidate switch in its environment (the factory would bind it)."""
    if latency_switches(environ)["single_candidate_fast"]:
        raise _single_candidate_refusal(consumer)


def require_value_means(bot, consumer):
    """``bot``, refused when its decision records may carry an unpriced
    candidate (``single_candidate_fast`` on); a consumer of ``value_means``
    never receives an unknown value in place of a number."""
    if getattr(bot, "single_candidate_fast", False):
        raise _single_candidate_refusal(consumer)
    return bot


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


class OracleWorldsError(PVSearchPolicyError):
    """The diagnostic oracle (module docstring) cannot supply the true deal: no
    harness hook is bound, or the hook's deal fails the world contract.  NEVER
    absorbed by the serving fallback: a diagnostic that silently played the
    heuristic would measure nothing."""


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
    # the history-legal world test (`ai.history_legality`); the same contract
    world_history_legal: bool = SAMPLER_DEFAULTS["world_history_legal"]
    # its draw-time form (`ai.history_legality.draw_constraints`; requires it)
    world_history_draw: bool = SAMPLER_DEFAULTS["world_history_draw"]
    # the S17 belief proposal inside that test (requires it); the same contract
    belief_worlds: bool = SAMPLER_DEFAULTS["belief_worlds"]
    # its capacity-aware draw (requires the proposal); the same contract
    belief_capacity: bool = SAMPLER_DEFAULTS["belief_capacity"]
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
    # its width (module docstring); the default is the payload's long-standing 32
    wide_lead_k: int = WIDE_LEAD_K
    finish_lead_admission: bool = False
    exact_lead_endgame: bool = False
    # its two optional variants (module docstring); each requires it
    exact_lead_tie_baseline: bool = False
    exact_lead_policy_first: bool = False
    # the deeper exact rule (module docstring): 0 is off
    exact_deep_cards: int = 0
    # DEV caps of the exact lead stage (``EXACT_LEAD_CAP_PARAMS``): the stage
    # deadline (needs ``exact_lead_endgame``) and the deeper rule's per-world
    # node cap (needs ``exact_deep_cards``); at their defaults ABSENT from the payload
    exact_lead_max_seconds: float = EXACT_LEAD_CAP_DEFAULTS["exact_lead_max_seconds"]
    exact_deep_max_nodes: int = EXACT_LEAD_CAP_DEFAULTS["exact_deep_max_nodes"]
    # DEV-only exact follow reranking; intentionally not exposed by factories.
    exact_follow: bool = False
    exact_follow_max_nodes: int = 250_000
    # its solver ("reference" or the compiled "compact-level" session,
    # `pv_exact_follow.SOLVERS`) and hand-card bound
    exact_follow_solver: str = "reference"
    exact_follow_max_cards: int = 4
    # the exact stages' world subset (module docstring): 0 = every world; a
    # subset at least ``worlds`` wide is the same search and ABSENT from the payload
    exact_world_subset: int = 0
    # the optional selection rule replacing the swap (exclusive with it); the same contract
    doomed_throw_reselect: bool = DOOMED_THROW_RESELECT_DEFAULTS["doomed_throw_reselect"]
    # its exact-stage guard (requires it and ``exact_lead_endgame``); the same contract
    doomed_throw_reselect_exact_guard: bool = \
        DOOMED_THROW_RESELECT_EXACT_GUARD_DEFAULTS["doomed_throw_reselect_exact_guard"]
    # the optional value-leaf finisher (refused with the tree or adaptive worlds); the same contract
    leaf_greedy_finish: bool = LEAF_GREEDY_DEFAULTS["leaf_greedy_finish"]
    # its exact-stage yield (requires it and an exact stage); the same contract
    leaf_greedy_finish_exact_skip: bool = \
        LEAF_GREEDY_EXACT_SKIP_DEFAULTS["leaf_greedy_finish_exact_skip"]
    leaf_greedy_deadline_ms: int = 0
    # its top-m restriction (module docstring): 0 is off and ABSENT from the payload
    leaf_greedy_top: int = 0
    # the held-out lead confirmation (`PVSearchBot` docstring): 0 is off and ABSENT
    # from the payload
    lead_confirm: int = 0
    # the optional declaration rule and its two parameters; the same contract
    # (the parameters too are ABSENT from the payload while the rule is off)
    value_declare: bool = VALUE_DECLARE_DEFAULTS["value_declare"]
    value_declare_worlds: int = VALUE_DECLARE_DEFAULTS["value_declare_worlds"]
    value_declare_margin: float = VALUE_DECLARE_DEFAULTS["value_declare_margin"]
    # its first-round gate widening (requires ``value_declare``); the same contract
    value_declare_every_first: bool = VALUE_DECLARE_EVERY_FIRST_DEFAULTS["value_declare_every_first"]
    # the served bury in its worlds (requires ``value_declare`` and, checked where
    # the bury is known, the wide value-only chooser); the same contract
    value_declare_served_bury: bool = VALUE_DECLARE_SERVED_BURY_DEFAULTS["value_declare_served_bury"]
    # its pass-conditioned worlds (requires ``value_declare``); the same contract
    value_declare_pass_worlds: bool = VALUE_DECLARE_PASS_WORLDS_DEFAULTS["value_declare_pass_worlds"]
    # its wait option (requires ``value_declare``); the same contract
    value_declare_wait: bool = VALUE_DECLARE_WAIT_DEFAULTS["value_declare_wait"]
    # the model-free first-round declaration (exclusive with ``value_declare``); the same contract
    declare_asap_first: bool = DECLARE_ASAP_DEFAULTS["declare_asap_first"]
    # the policy head playing the value leaf's first trick (module docstring; it
    # needs ``value_declare`` or a hybrid/value bury arm, checked where the arm is
    # known: the constructors and the registry); the same contract
    leaf_policy_first_trick: bool = LEAF_POLICY_DEFAULTS["leaf_policy_first_trick"]
    # DIAGNOSTIC ONLY (module docstring, #707 S16): the play worlds are the one
    # true deal from the screen harness's hook; never served; the same contract
    oracle_worlds: bool = ORACLE_WORLDS_DEFAULTS["oracle_worlds"]
    # DIAGNOSTIC ONLY (module docstring, #707 S17 step 3): the soft oracle's two
    # parameters, 0 = off and ABSENT from the payload; never served
    oracle_mix_k: int = ORACLE_SOFT_DEFAULTS["oracle_mix_k"]
    oracle_pin_q: float = ORACLE_SOFT_DEFAULTS["oracle_pin_q"]
    # the belief package of ``belief_worlds`` (its full sha256); None, and ABSENT
    # from the payload, while the rule is off
    belief_sha256: str | None = None


# Keep configuration validation independent of the optional exact-follow
# implementation.  The latter imports the native endgame solver, which is
# needed only when the DEV stage is actually enabled.
_EXACT_FOLLOW_SOLVERS = ("reference", "compact-level")


def _check_value_declare_params(worlds, margin):
    if type(worlds) is not int or worlds < 1:
        raise PVSearchPolicyError("value_declare_worlds must be a positive int")
    if type(margin) not in (int, float) or not math.isfinite(margin) or margin < 0:
        raise PVSearchPolicyError("value_declare_margin must be a finite number >= 0")


def _check_exact_deep_cards(cards) -> None:
    lo, hi = EXACT_DEEP_CARDS_RANGE
    if isinstance(cards, bool) or type(cards) is not int or not (cards == 0 or lo <= cards <= hi):
        raise PVSearchPolicyError(f"exact_deep_cards must be 0 (off) or an int in [{lo}, {hi}]")


def _check_exact_lead_caps(config) -> tuple[bool, bool]:
    """Validate the two DEV caps; returns which of them differ from their
    defaults.  A lifted cap whose stage is off would change the identity of a
    recipe whose decisions it cannot change, so it is refused."""
    seconds, nodes = config.exact_lead_max_seconds, config.exact_deep_max_nodes
    lo, hi = EXACT_LEAD_MAX_SECONDS_RANGE
    if (isinstance(seconds, bool) or type(seconds) not in (int, float)
            or not math.isfinite(seconds) or not lo <= seconds <= hi):
        raise PVSearchPolicyError(
            f"exact_lead_max_seconds must be a finite number in [{lo}, {hi}]")
    lo, hi = EXACT_DEEP_MAX_NODES_RANGE
    if isinstance(nodes, bool) or type(nodes) is not int or not lo <= nodes <= hi:
        raise PVSearchPolicyError(f"exact_deep_max_nodes must be an int in [{lo}, {hi}]")
    lifted_seconds = seconds != EXACT_LEAD_CAP_DEFAULTS["exact_lead_max_seconds"]
    lifted_nodes = nodes != EXACT_LEAD_CAP_DEFAULTS["exact_deep_max_nodes"]
    if lifted_seconds and not config.exact_lead_endgame:
        raise PVSearchPolicyError("exact_lead_max_seconds needs exact_lead_endgame "
                                  "(SHENGJI_PV_EXACT_LEAD_MAX_SECONDS needs "
                                  "SHENGJI_PV_EXACT_LEAD_ENDGAME=1)")
    if lifted_nodes and not config.exact_deep_cards:
        raise PVSearchPolicyError("exact_deep_max_nodes needs exact_deep_cards "
                                  "(SHENGJI_PV_EXACT_DEEP_MAX_NODES needs "
                                  "SHENGJI_PV_EXACT_DEEP_CARDS)")
    return lifted_seconds, lifted_nodes


def exact_lead_cap_tokens(config) -> str:
    """The name tokens of lifted caps, ``""`` at the defaults: ``-els<ms>`` for
    the stage deadline in whole milliseconds and ``-edn<nodes>`` for the node cap
    (the digest carries the exact values)."""
    lifted_seconds, lifted_nodes = _check_exact_lead_caps(config)
    tokens = ""
    if lifted_seconds:
        tokens += f"-els{round(config.exact_lead_max_seconds * 1000)}"
    if lifted_nodes:
        tokens += f"-edn{config.exact_deep_max_nodes}"
    return tokens


def _check_exact_follow_params(config: PVSearchConfig) -> None:
    """Validate DEV exact-follow knobs before package/factory work."""
    if type(config.exact_follow) is not bool:
        raise PVSearchPolicyError("exact_follow must be a bool")
    if type(config.exact_follow_max_nodes) is not int or config.exact_follow_max_nodes < 1:
        raise PVSearchPolicyError("exact_follow_max_nodes must be a positive int")
    if config.exact_follow_solver not in _EXACT_FOLLOW_SOLVERS:
        raise PVSearchPolicyError(
            f"exact_follow_solver must be one of {_EXACT_FOLLOW_SOLVERS}")
    if (isinstance(config.exact_follow_max_cards, bool)
            or type(config.exact_follow_max_cards) is not int
            or not 1 <= config.exact_follow_max_cards <= 8):
        raise PVSearchPolicyError("exact_follow_max_cards must be an int in [1, 8]")


def _check_exact_world_subset(config) -> int:
    """The subset width the exact stages use, 0 when every world is used (off,
    or a subset at least ``worlds`` wide); refuses a malformed width and an
    active subset without an exact stage."""
    n = config.exact_world_subset
    if isinstance(n, bool) or type(n) is not int or not 0 <= n <= 512:
        raise PVSearchPolicyError("exact_world_subset must be an int in [0, 512]")
    if not n or n >= config.worlds:
        return 0
    if not (config.exact_lead_endgame or config.exact_follow):
        raise PVSearchPolicyError(_EXACT_WORLD_SUBSET_REQUIRES)
    return n


def _check_leaf_greedy_top(config) -> int:
    """The top-m width, 0 when off; refuses a malformed value and one without
    ``leaf_greedy_finish``."""
    m = config.leaf_greedy_top
    lo, hi = LEAF_GREEDY_TOP_RANGE
    if isinstance(m, bool) or type(m) is not int or not (m == 0 or lo <= m <= hi):
        raise PVSearchPolicyError(f"leaf_greedy_top must be 0 (off) or an int in [{lo}, {hi}]")
    if m and not config.leaf_greedy_finish:
        raise PVSearchPolicyError(_LEAF_GREEDY_TOP_REQUIRES)
    return m


def _check_wide_lead_k(config) -> int:
    """The lead admission width; refuses a malformed value and a non-default
    one without ``wide_lead_admission``."""
    k = config.wide_lead_k
    lo, hi = WIDE_LEAD_K_RANGE
    if isinstance(k, bool) or type(k) is not int or not lo <= k <= hi:
        raise PVSearchPolicyError(f"wide_lead_k must be an int in [{lo}, {hi}]")
    if k != WIDE_LEAD_K and not config.wide_lead_admission:
        raise PVSearchPolicyError("wide_lead_k needs wide_lead_admission "
                                  "(SHENGJI_PV_WIDE_LEAD_K needs SHENGJI_PV_WIDE_LEAD_ADMISSION=1)")
    return k


def _check_lead_confirm(config) -> int:
    """The confirmation pool width ``k``, 0 when off; refuses a malformed value,
    one not wider than ``candidates``, and the tree and adaptive worlds (their
    reducers re-select on a matrix this rule does not see)."""
    k = config.lead_confirm
    lo, hi = LEAD_CONFIRM_K_RANGE
    if isinstance(k, bool) or type(k) is not int or not (k == 0 or lo <= k <= hi):
        raise PVSearchPolicyError(f"lead_confirm must be 0 (off) or an int in [{lo}, {hi}]")
    if not k:
        return 0
    if k <= config.candidates:
        raise PVSearchPolicyError("lead_confirm must exceed candidates (the served ballot width)")
    if config.tree is not None or config.adaptive_worlds or config.adaptive_worlds_leads:
        raise PVSearchPolicyError(_LEAD_CONFIRM_EXCLUSIVE)
    return k


def _check_leaf_greedy_deadline(config) -> int:
    """The finish deadline in ms, 0 when off; refuses a malformed value and
    one without ``leaf_greedy_finish``."""
    ms = config.leaf_greedy_deadline_ms
    lo, hi = LEAF_GREEDY_DEADLINE_MS_RANGE
    if isinstance(ms, bool) or type(ms) is not int or not (ms == 0 or lo <= ms <= hi):
        raise PVSearchPolicyError(
            f"leaf_greedy_deadline_ms must be 0 (off) or an int in [{lo}, {hi}]")
    if ms and not config.leaf_greedy_finish:
        raise PVSearchPolicyError(_LEAF_GREEDY_DEADLINE_REQUIRES)
    return ms


def recipe_payload(config: PVSearchConfig) -> dict:
    """The digested recipe: every field, except that an optional rule that is
    OFF is omitted (the payload of the pre-rule recipe, byte for byte) and a
    rule that is on carries its parameters."""
    payload = asdict(config)
    _check_exact_follow_params(config)
    # Disabled follow-stage knobs do not change existing serving identities.
    # Enabled recipes retain all parameters in their digest.
    if not config.exact_follow:
        payload.pop("exact_follow_max_nodes", None)
        payload.pop("exact_follow_solver", None)
        payload.pop("exact_follow_max_cards", None)
    del payload["exact_world_subset"]
    subset = _check_exact_world_subset(config)
    if subset:
        payload["exact_world_subset"] = {"worlds": subset, **EXACT_WORLD_SUBSET_RULE}
    if config.tree is None:
        del payload["tree"]
    elif not isinstance(config.tree, PVTreeConfig):
        raise PVSearchPolicyError("tree must be a PVTreeConfig or None")
    for key in RULE_FLAGS.values():
        if type(payload[key]) is not bool:
            raise PVSearchPolicyError(f"{key} must be a bool")
        if not payload[key]:
            del payload[key]
    belief_sha = payload.pop("belief_sha256")
    if config.belief_capacity and not config.belief_worlds:
        raise PVSearchPolicyError(_BELIEF_CAPACITY_REQUIRES)
    if config.belief_worlds:
        if not (config.world_history_legal and config.world_history_draw):
            raise PVSearchPolicyError(_BELIEF_REQUIRES)
        if (not isinstance(belief_sha, str) or len(belief_sha) != 64
                or any(c not in "0123456789abcdef" for c in belief_sha)):
            raise PVSearchPolicyError("belief_worlds needs the belief package's full sha256 "
                                      "(SHENGJI_PV_BELIEF_SHA256)")
        payload["belief_worlds_package"] = {"schema": BELIEF_SCHEMA, "sha256": belief_sha,
                                            "proposal": (BELIEF_PROPOSAL_CAPACITY
                                                         if config.belief_capacity
                                                         else BELIEF_PROPOSAL),
                                            "prep_seconds": BELIEF_PREP_SECONDS,
                                            "fallback": "history-legal-production-draw"}
    elif belief_sha is not None:
        raise PVSearchPolicyError("belief_sha256 needs belief_worlds (SHENGJI_PV_BELIEF_WORLDS=1)")
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
        payload["wide_lead_k"] = _check_wide_lead_k(config)
    else:
        _check_wide_lead_k(config)
        del payload["wide_lead_k"]
    if config.exact_lead_endgame:
        if (config.tree is not None or config.adaptive_worlds or config.adaptive_worlds_leads
                or config.oracle_worlds or config.oracle_mix_k or config.oracle_pin_q):
            raise PVSearchPolicyError('exact_lead_endgame excludes tree, adaptive worlds and oracle worlds')
        payload['exact_lead_limits'] = EXACT_LEAD_LIMITS
    # the DEV caps enter the payload only through the limits they replace
    lifted_seconds, lifted_nodes = _check_exact_lead_caps(config)
    for key in EXACT_LEAD_CAP_PARAMS.values():
        del payload[key]
    if lifted_seconds:
        payload['exact_lead_limits'] = {**EXACT_LEAD_LIMITS,
                                        'max_seconds': float(config.exact_lead_max_seconds)}
    if (config.exact_lead_tie_baseline or config.exact_lead_policy_first
            or config.exact_deep_cards) \
            and not config.exact_lead_endgame:
        raise PVSearchPolicyError(_EXACT_LEAD_VARIANT_REQUIRES)
    _check_exact_deep_cards(config.exact_deep_cards)
    if config.exact_deep_cards:
        payload['exact_deep_limits'] = EXACT_DEEP_LIMITS
        if lifted_nodes:
            payload['exact_deep_limits'] = {**EXACT_DEEP_LIMITS,
                                            'max_nodes': config.exact_deep_max_nodes}
    else:
        del payload['exact_deep_cards']
    if config.exact_lead_tie_baseline:
        payload['exact_lead_tie_rule'] = EXACT_LEAD_TIE_RULE
    if config.exact_lead_policy_first:
        payload['exact_lead_policy_first_limits'] = EXACT_LEAD_POLICY_LIMITS
    if config.finish_lead_admission:
        if config.tree is not None:
            raise PVSearchPolicyError('finish_lead_admission does not combine with the tree')
        payload['finish_lead_max_cards'] = FINISH_LEAD_MAX_CARDS
    if config.lead_tiebreak_prior:
        payload["lead_tiebreak_epsilon"] = LEAD_TIEBREAK_DEFAULTS["lead_tiebreak_epsilon"]
    if config.doomed_throw_swap and config.doomed_throw_reselect:
        raise PVSearchPolicyError(_DOOMED_THROW_EXCLUSIVE)
    if config.doomed_throw_reselect and config.tree is not None:
        # the tree re-selects on its own Q matrix after `_select`
        raise PVSearchPolicyError("doomed_throw_reselect does not combine with the tree "
                                  "(SHENGJI_PV_DOOMED_THROW_RESELECT=1 with SHENGJI_PV_TREE_SIMS)")
    if config.doomed_throw_reselect_exact_guard:
        if not (config.doomed_throw_reselect and config.exact_lead_endgame):
            raise PVSearchPolicyError(_DOOMED_THROW_RESELECT_EXACT_GUARD_REQUIRES)
        payload["doomed_throw_reselect_exact_rule"] = DOOMED_THROW_RESELECT_EXACT_RULE
    if config.leaf_greedy_finish:
        if config.tree is not None or config.adaptive_worlds or config.adaptive_worlds_leads:
            raise PVSearchPolicyError(_LEAF_GREEDY_EXCLUSIVE)
        payload["leaf_finish"] = LEAF_GREEDY_FINISH_RULE
    if config.leaf_greedy_finish_exact_skip:
        if not (config.leaf_greedy_finish
                and (config.exact_lead_endgame or config.exact_follow)):
            raise PVSearchPolicyError(_LEAF_GREEDY_EXACT_SKIP_REQUIRES)
        payload["leaf_finish_exact_rule"] = LEAF_GREEDY_EXACT_SKIP_RULE_ID
    deadline_ms = _check_leaf_greedy_deadline(config)
    del payload["leaf_greedy_deadline_ms"]
    top = _check_leaf_greedy_top(config)
    del payload["leaf_greedy_top"]
    if top:
        payload["leaf_greedy_top"] = {"m": top, "rule": LEAF_GREEDY_TOP_RULE_ID,
                                      "offset": LEAF_GREEDY_TOP_OFFSET}
    if deadline_ms:
        payload["leaf_greedy_deadline"] = {"ms": deadline_ms, "rule": LEAF_GREEDY_DEADLINE_RULE_ID}
    confirm = _check_lead_confirm(config)
    del payload["lead_confirm"]
    if confirm:
        payload["lead_confirm"] = {"k": confirm, "rule": LEAD_CONFIRM_RULE_ID, **LEAD_CONFIRM_PARAMS}
    if config.adaptive_worlds and config.adaptive_worlds_leads:
        raise PVSearchPolicyError(_ADAPTIVE_WORLDS_EXCLUSIVE)
    if config.oracle_worlds and (config.adaptive_worlds or config.adaptive_worlds_leads):
        raise PVSearchPolicyError(_ORACLE_ADAPTIVE_EXCLUSIVE)
    if config.world_history_draw and not config.world_history_legal:
        raise PVSearchPolicyError("world_history_draw requires world_history_legal "
                                  "(SHENGJI_PV_WORLD_HISTORY_DRAW=1 needs "
                                  "SHENGJI_PV_WORLD_HISTORY_LEGAL=1)")
    if config.world_history_legal and (config.oracle_worlds or config.oracle_mix_k
                                       or config.oracle_pin_q):
        raise PVSearchPolicyError(_HISTORY_LEGAL_ORACLE_EXCLUSIVE)
    if config.oracle_worlds:
        # the digest says what the one world is; a reader never has to infer it
        payload["oracle_worlds_information"] = "true-deal"
    mix_k, pin_q = _check_soft_oracle(config)
    for key in ORACLE_SOFT_PARAMS.values():
        del payload[key]
    if mix_k:
        payload.update(oracle_mix_k=mix_k,
                       oracle_worlds_information=soft_oracle.MIX_INFORMATION)
    if pin_q:
        payload.update(oracle_pin_q=pin_q, oracle_worlds_information=soft_oracle.PIN_INFORMATION,
                       oracle_pin_fill=soft_oracle.PIN_FILL,
                       oracle_pin_fill_attempts=soft_oracle.PIN_FILL_ATTEMPTS)
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
    _check_value_declare_params(config.value_declare_worlds, config.value_declare_margin)
    if config.value_declare:
        payload["value_declare_margin"] = float(config.value_declare_margin)
        payload["value_declare_model"] = (value_declare_model.MODEL_POLICY_FIRST_TRICK
                                          if config.leaf_policy_first_trick
                                          else value_declare_model.MODEL)
        if config.value_declare_served_bury:
            payload["value_declare_model"] = payload["value_declare_model"].replace(
                value_declare_model.MODEL_HEURISTIC_BURY, declare_served_bury.MODEL_BURY)
            payload.update(value_declare_served_bury_k=declare_served_bury.K_DEFAULT,
                           value_declare_served_bury_model_worlds=(
                               declare_served_bury.MODEL_WORLDS_DEFAULT),
                           value_declare_served_bury_worlds=declare_served_bury.WORLDS_DEFAULT,
                           value_declare_served_bury_outcomes=declare_served_bury.OUTCOMES)
        if config.value_declare_pass_worlds:
            payload["value_declare_model"] = payload["value_declare_model"].replace(
                "uniform-unseen", declare_pass_worlds.MODEL_UNSEEN)
            payload.update(value_declare_pass_hazard=declare_pass_worlds.HAZARD,
                           value_declare_pass_max_attempts=declare_pass_worlds.MAX_ATTEMPTS)
        if config.value_declare_wait:
            payload.update(value_declare_wait_model=declare_wait.MODEL,
                           value_declare_wait_worlds=declare_wait.WORLDS_DEFAULT,
                           value_declare_wait_inner_worlds=declare_wait.INNER_WORLDS_DEFAULT)
    else:
        if (config.value_declare_worlds != VALUE_DECLARE_DEFAULTS["value_declare_worlds"]
                or config.value_declare_margin != VALUE_DECLARE_DEFAULTS["value_declare_margin"]):
            raise PVSearchPolicyError("value_declare_worlds / value_declare_margin need "
                                      "value_declare (SHENGJI_PV_VALUE_DECLARE=1)")
        del payload["value_declare_worlds"], payload["value_declare_margin"]
    if config.value_declare_every_first and not config.value_declare:
        raise PVSearchPolicyError(_VALUE_DECLARE_EVERY_FIRST_REQUIRES)
    if config.value_declare_served_bury and not config.value_declare:
        raise PVSearchPolicyError(_VALUE_DECLARE_SERVED_BURY_REQUIRES)
    if config.value_declare_pass_worlds and not config.value_declare:
        raise PVSearchPolicyError(_VALUE_DECLARE_PASS_WORLDS_REQUIRES)
    if config.value_declare_wait and not config.value_declare:
        raise PVSearchPolicyError(_VALUE_DECLARE_WAIT_REQUIRES)
    if config.declare_asap_first and config.value_declare:
        raise PVSearchPolicyError(_DECLARE_ASAP_EXCLUSIVE)
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
    tokens = [token for field, token in RULE_TOKENS if getattr(config, field)]
    deadline_ms = _check_leaf_greedy_deadline(config)
    if deadline_ms:
        # right after the greedy leaf's own tokens
        tokens.insert(tokens.index("lgfx" if "lgfx" in tokens else "lgf") + 1,
                      f"{LEAF_GREEDY_DEADLINE_TOKEN}{deadline_ms}")
    top = _check_leaf_greedy_top(config)
    if top:
        # right after the greedy leaf's own tokens, the deadline included
        last = max(i for i, t in enumerate(tokens)
                   if t in ("lgf", "lgfx") or t.startswith(LEAF_GREEDY_DEADLINE_TOKEN))
        tokens.insert(last + 1, f"{LEAF_GREEDY_TOP_TOKEN}{top}")
    if config.wide_lead_admission and _check_wide_lead_k(config) != WIDE_LEAD_K:
        tokens[tokens.index("wla")] = f"wla{config.wide_lead_k}"
    rules = "".join(f"-{token}" for token in tokens)
    # the soft oracle's token after the rule tokens; "" while off
    if config.exact_deep_cards:
        rules += f"-ed{config.exact_deep_cards}"
    rules += exact_lead_cap_tokens(config)   # "" at the default caps
    if config.oracle_mix_k:
        rules += f"-{soft_oracle.mix_token(config.oracle_mix_k)}"
    if config.oracle_pin_q:
        rules += f"-{soft_oracle.pin_token(config.oracle_pin_q)}"
    if config.exact_follow:
        rules += f"-xf{config.exact_follow_max_cards}"
        if config.exact_follow_solver != "reference":
            rules += f"-xf{config.exact_follow_solver.replace('-', '')}"
    subset = _check_exact_world_subset(config)
    if subset:
        rules += f"-{EXACT_WORLD_SUBSET_TOKEN}{subset}"
    confirm = _check_lead_confirm(config)
    if confirm:
        rules += f"-{LEAD_CONFIRM_TOKEN}{confirm}"
    rules += tree_token(config.tree)   # "" while the tree is off
    return (f"pv-search-{ckpt8}{prior}-w{config.worlds}-k{config.candidates}{rules}"
            f"-r{recipe_digest(config)}")


class _LeadConfirmLeafCut(Exception):
    """The lead confirmation's greedy finish passed its deadline (an abandon)."""


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

    Optional held-out lead confirmation ``lead_confirm`` (``SHENGJI_PV_LEAD_CONFIRM=<k>``,
    token ``lcc<k>``; OFF BY DEFAULT, and while off `_search` takes exactly the
    path it took before, draws nothing more and the record gains no key).  On a
    LEAD whose base decision is final (the served ballot, value pass, selection
    rules and doomed-throw re-select, unchanged) and on which no exact lead
    stage runs: the pool is the policy's next ``k - k_used`` finite-preference
    actions outside the ballot.  The served lead and the pool are priced on the
    served leaf over the first ``screen_worlds`` of the base worlds; at most
    ``challengers`` pool actions whose screen mean beats the served lead's (best
    first; a doomed throw skipped under ``doomed_throw_reselect``) go on.  Those
    and the served lead are priced again on ``rounds`` FRESH draws of W worlds
    from this bot's own sampler, and a challenger replaces the served lead only
    when its paired mean difference there exceeds ``z`` paired standard errors
    plus ``margin`` (the largest such difference wins).  The fresh worlds never
    took part in choosing the challenger, so the confirmation is not inflated by
    the screen's selection among the pool (`LEAD_CONFIRM_PARAMS`).  Budget: as
    ``adaptive_worlds``, through `optional_stage.OptionalStage` -- it starts only
    below ``start_fraction`` of the serving budget, every check tests the hard
    budget then a soft deadline at ``soft_fraction``, a greedy finish cut by
    its deadline abandons, and any abandon plays the base decision with its
    records.  Record (leads only, rule on): ``lead_confirm_status``
    (``applied`` / ``rejected`` / ``no_challenger`` / ``no_pool`` /
    ``skipped_budget`` / ``abandoned`` / ``exact`` / ``override`` /
    ``single_candidate``), ``_pool``, ``_screen_worlds``, ``_challengers``,
    ``_screen_margins``, ``_worlds`` (fresh), ``_deltas``, ``_ses``,
    ``_applied``, ``_to`` and ``_seconds`` (+ ``_abandon_reason`` / ``_error``).
    An applied challenger is appended to the admitted ballot with a None value
    mean and is the selected index; ``value_means`` is otherwise the base pass's.

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
    value_declare = VALUE_DECLARE_DEFAULTS["value_declare"]
    value_declare_worlds = VALUE_DECLARE_DEFAULTS["value_declare_worlds"]
    value_declare_margin = VALUE_DECLARE_DEFAULTS["value_declare_margin"]
    value_declare_every_first = VALUE_DECLARE_EVERY_FIRST_DEFAULTS["value_declare_every_first"]
    value_declare_served_bury = VALUE_DECLARE_SERVED_BURY_DEFAULTS["value_declare_served_bury"]
    value_declare_pass_worlds = VALUE_DECLARE_PASS_WORLDS_DEFAULTS["value_declare_pass_worlds"]
    value_declare_wait = VALUE_DECLARE_WAIT_DEFAULTS["value_declare_wait"]
    declare_asap_first = DECLARE_ASAP_DEFAULTS["declare_asap_first"]
    leaf_policy_first_trick = LEAF_POLICY_DEFAULTS["leaf_policy_first_trick"]
    #: the greedy leaf's exact-stage yield (module docstring): class-level OFF;
    #: its per-decision flag (this decision's value pass scores `_leaf`) is
    #: instance state of an ON bot only
    leaf_greedy_finish_exact_skip = LEAF_GREEDY_EXACT_SKIP_DEFAULTS["leaf_greedy_finish_exact_skip"]
    #: the finish deadline (module docstring), 0 = off; instance state of an ON bot only
    leaf_greedy_deadline_ms = 0
    _leaf_greedy_exact_skipped = False
    #: the finish's top-m restriction (module docstring), 0 = off; instance state
    #: of an ON bot only, as is its per-decision record and pruned-leaf set
    leaf_greedy_top = 0
    _leaf_greedy_top = None
    _leaf_greedy_pruned = frozenset()
    _leaf_greedy_plain_pass = False
    #: the lead admission width of ``wide_lead_admission``; instance state only
    #: when it differs from the default
    wide_lead_k = WIDE_LEAD_K
    #: the held-out lead confirmation (class docstring), 0 = off; instance state
    #: of an ON bot only, as is its per-decision record.  Its parameters are the
    #: digested `LEAD_CONFIRM_PARAMS`
    lead_confirm = 0
    _lead_confirm = None
    lead_confirm_screen_worlds = LEAD_CONFIRM_PARAMS["screen_worlds"]
    lead_confirm_challengers = LEAD_CONFIRM_PARAMS["challengers"]
    lead_confirm_rounds = LEAD_CONFIRM_PARAMS["rounds"]
    lead_confirm_z = LEAD_CONFIRM_PARAMS["z"]
    lead_confirm_margin = LEAD_CONFIRM_PARAMS["margin"]
    lead_confirm_start_fraction = LEAD_CONFIRM_PARAMS["start_fraction"]
    lead_confirm_soft_fraction = LEAD_CONFIRM_PARAMS["soft_fraction"]
    #: the exact lead's two optional variants (module docstring): class-level OFF
    exact_lead_tie_baseline = False
    exact_lead_policy_first = False
    exact_deep_cards = 0
    #: the exact lead stage's DEV caps: class-level defaults, instance state only
    #: when lifted
    exact_lead_max_seconds = EXACT_LEAD_CAP_DEFAULTS["exact_lead_max_seconds"]
    exact_deep_max_nodes = EXACT_LEAD_CAP_DEFAULTS["exact_deep_max_nodes"]
    #: the belief proposal's log (module docstring), ON by default; it is read
    #: only while ``belief_worlds`` is on and enters no name or digest
    belief_log = BELIEF_LOG_DEFAULT
    #: the latency switches (module docstring), OFF by default; like the
    #: belief log they enter no name or digest, and none changes a decision
    #: (``leaf_greedy_stream`` is declared on `PolicyValueBot`).
    #: Instance state of an ON bot only.
    encode_prefix_cache = False
    encode_batch_fast = False
    legal_native = False
    encode_native = False
    leaf_cache_release = False
    leaf_clone_fast = False
    leaf_trick_cache = False
    world_fast = False
    single_candidate_fast = False
    #: the exact stages' world subset (module docstring): 0 = every world
    exact_world_subset = 0
    #: the diagnostic oracle (module docstring) and its harness hook: a callable
    #: ``(rnd, seat) -> (hands, buried)`` bound ONLY by `bind_oracle_deal` (the
    #: screen harness); None = unbound, and an oracle bot then refuses to play
    oracle_worlds = ORACLE_WORLDS_DEFAULTS["oracle_worlds"]
    _oracle_deal = None
    #: its soft variants (module docstring, #707 S17 step 3): 0 = off; the
    #: last decision's scalar telemetry (None while off)
    oracle_mix_k = ORACLE_SOFT_DEFAULTS["oracle_mix_k"]
    oracle_pin_q = ORACLE_SOFT_DEFAULTS["oracle_pin_q"]
    _soft_oracle = None
    _soft_oracle_drawn_at = None
    #: the soft oracle's CUMULATIVE construction work (`SOFT_ORACLE_COUNTERS`),
    #: incremented as the work happens so a decision aborted by the budget or
    #: an error keeps what it spent; read by the screen's `work_counters`.
    #: Instance state of an ON bot only (absent while off)
    soft_oracle_counts = None
    #: the bury arm a subclass binds BEFORE `__init__` (`PVSearchBuryBot`), so the
    #: leaf rule's effect check knows whether a bury leaf exists; None = no bury arm
    _leaf_bury_arm = None
    #: set (only with ``value_declare`` or ``declare_asap_first`` on) by every
    #: `decide_declare` call: the decision's record when the rule's gate
    #: admitted it (asap: when it declared), else None
    last_declare_record = None

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
                         doomed_throw_reselect=config.doomed_throw_reselect,
                         doomed_throw_reselect_exact_guard=config.doomed_throw_reselect_exact_guard,
                         leaf_greedy_finish=config.leaf_greedy_finish)
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
        # the history-legal world test (`ai.history_legality`): a sampled world
        # must make every earlier follow by another seat legal
        self.world_history_legal = bool(config.world_history_legal)
        # its draw-time form: the pair obligation's twins are never dealt
        self.world_history_draw = bool(config.world_history_draw)
        if self.world_history_draw and not self.world_history_legal:
            raise PVSearchPolicyError("world_history_draw requires world_history_legal")
        # the S17 belief proposal inside the history-legal draw; its package is
        # bound by `make_pv_search_bot` (None: every decision falls back)
        self.belief_worlds = bool(config.belief_worlds)
        if self.belief_worlds and not (self.world_history_legal and self.world_history_draw):
            raise PVSearchPolicyError(_BELIEF_REQUIRES)
        self.belief_model = None
        # the proposal's capacity-aware draw (requires the proposal)
        self.belief_capacity = bool(config.belief_capacity)
        if self.belief_capacity and not self.belief_worlds:
            raise PVSearchPolicyError(_BELIEF_CAPACITY_REQUIRES)
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
        if _check_wide_lead_k(config) != WIDE_LEAD_K:
            self.wide_lead_k = config.wide_lead_k
        if type(config.finish_lead_admission) is not bool:
            raise PVSearchPolicyError('finish_lead_admission must be a bool')
        if config.finish_lead_admission and config.tree is not None:
            raise PVSearchPolicyError('finish_lead_admission does not combine with the tree')
        self.finish_lead_admission = config.finish_lead_admission
        if type(config.exact_lead_endgame) is not bool:
            raise PVSearchPolicyError('exact_lead_endgame must be a bool')
        if config.exact_lead_endgame and (config.tree is not None or config.adaptive_worlds
                                        or config.adaptive_worlds_leads or config.oracle_worlds
                                        or config.oracle_mix_k or config.oracle_pin_q):
            raise PVSearchPolicyError('exact_lead_endgame excludes tree, adaptive worlds and oracle worlds')
        self.exact_lead_endgame = config.exact_lead_endgame
        self._exact_lead = None
        for key in EXACT_LEAD_VARIANT_RULES.values():
            if type(getattr(config, key)) is not bool:
                raise PVSearchPolicyError(f'{key} must be a bool')
            if getattr(config, key):
                if not config.exact_lead_endgame:
                    raise PVSearchPolicyError(_EXACT_LEAD_VARIANT_REQUIRES)
                # instance state only when on: a flag-off bot is exactly S18's
                setattr(self, key, True)
        _check_exact_deep_cards(config.exact_deep_cards)
        if config.exact_deep_cards:
            if not config.exact_lead_endgame:
                raise PVSearchPolicyError(_EXACT_LEAD_VARIANT_REQUIRES)
            self.exact_deep_cards = config.exact_deep_cards
        lifted_seconds, lifted_nodes = _check_exact_lead_caps(config)
        if lifted_seconds:
            self.exact_lead_max_seconds = float(config.exact_lead_max_seconds)
        if lifted_nodes:
            self.exact_deep_max_nodes = config.exact_deep_max_nodes
        if type(config.exact_follow) is not bool:
            raise PVSearchPolicyError("exact_follow must be a bool")
        if type(config.exact_follow_max_nodes) is not int or config.exact_follow_max_nodes < 1:
            raise PVSearchPolicyError("exact_follow_max_nodes must be a positive int")
        self.exact_follow = config.exact_follow
        self.exact_follow_max_nodes = config.exact_follow_max_nodes
        if config.exact_follow_solver not in _EXACT_FOLLOW_SOLVERS:
            raise PVSearchPolicyError(
                f"exact_follow_solver must be one of {_EXACT_FOLLOW_SOLVERS}")
        if (type(config.exact_follow_max_cards) is not int
                or not 1 <= config.exact_follow_max_cards <= 8):
            raise PVSearchPolicyError("exact_follow_max_cards must be an int in [1, 8]")
        self.exact_follow_solver = config.exact_follow_solver
        self.exact_follow_max_cards = config.exact_follow_max_cards
        subset = _check_exact_world_subset(config)
        if subset:
            # instance state only when active: an inactive bot's attributes are unchanged
            self.exact_world_subset = subset
        if self.exact_follow and (config.tree is not None or config.adaptive_worlds
                                  or config.adaptive_worlds_leads):
            raise PVSearchPolicyError(
                "exact_follow does not combine with tree or adaptive_worlds")
        self._exact_follow_state = None
        self._finish_lead_added = False
        self._wide_lead = None
        if config.doomed_throw_reselect and config.tree is not None:
            raise PVSearchPolicyError("doomed_throw_reselect does not combine with the tree")
        if config.doomed_throw_reselect_exact_guard and not config.exact_lead_endgame:
            raise PVSearchPolicyError(_DOOMED_THROW_RESELECT_EXACT_GUARD_REQUIRES)
        if config.leaf_greedy_finish and (config.tree is not None or config.adaptive_worlds
                                          or config.adaptive_worlds_leads):
            raise PVSearchPolicyError(_LEAF_GREEDY_EXCLUSIVE)
        if type(config.leaf_greedy_finish_exact_skip) is not bool:
            raise PVSearchPolicyError("leaf_greedy_finish_exact_skip must be a bool")
        if config.leaf_greedy_finish_exact_skip:
            if not (config.leaf_greedy_finish
                    and (config.exact_lead_endgame or config.exact_follow)):
                raise PVSearchPolicyError(_LEAF_GREEDY_EXACT_SKIP_REQUIRES)
            # instance state only when on: a flag-off bot's attributes are unchanged
            self.leaf_greedy_finish_exact_skip = True
        deadline_ms = _check_leaf_greedy_deadline(config)
        if deadline_ms:
            self.leaf_greedy_deadline_ms = deadline_ms
        top = _check_leaf_greedy_top(config)
        if top:
            self.leaf_greedy_top = top
        confirm = _check_lead_confirm(config)
        if confirm:
            if type(self)._value_means is not PVSearchBot._value_means:
                raise PVSearchPolicyError(f"lead_confirm needs serving's own _value_means; "
                                          f"{type(self).__name__} replaces it")
            self.lead_confirm = confirm
        if type(config.value_declare) is not bool:
            raise PVSearchPolicyError("value_declare must be a bool")
        _check_value_declare_params(config.value_declare_worlds, config.value_declare_margin)
        if config.value_declare:
            # instance state only when on: a flag-off bot's attributes (the
            # screen worker's checkpointed state) are exactly what they were
            self.value_declare = True
            self.value_declare_worlds = config.value_declare_worlds
            self.value_declare_margin = float(config.value_declare_margin)
        for key in ("value_declare_every_first", "value_declare_served_bury",
                    "value_declare_pass_worlds", "value_declare_wait",
                    "declare_asap_first"):
            if type(getattr(config, key)) is not bool:
                raise PVSearchPolicyError(f"{key} must be a bool")
        if config.value_declare_every_first and not config.value_declare:
            raise PVSearchPolicyError(_VALUE_DECLARE_EVERY_FIRST_REQUIRES)
        if config.value_declare_served_bury:
            if not config.value_declare:
                raise PVSearchPolicyError(_VALUE_DECLARE_SERVED_BURY_REQUIRES)
            if self._leaf_bury_arm not in BURY_MODEL_ARMS:
                # the wide chooser itself is checked by `PVSearchBuryBot`
                raise PVSearchPolicyError(_VALUE_DECLARE_SERVED_BURY_NO_EFFECT)
            self.value_declare_served_bury = True
        if config.value_declare_pass_worlds:
            if not config.value_declare:
                raise PVSearchPolicyError(_VALUE_DECLARE_PASS_WORLDS_REQUIRES)
            self.value_declare_pass_worlds = True
        if config.value_declare_wait:
            if not config.value_declare:
                raise PVSearchPolicyError(_VALUE_DECLARE_WAIT_REQUIRES)
            self.value_declare_wait = True
        if config.declare_asap_first and config.value_declare:
            raise PVSearchPolicyError(_DECLARE_ASAP_EXCLUSIVE)
        if config.value_declare_every_first:
            self.value_declare_every_first = True
        if config.declare_asap_first:
            self.declare_asap_first = True
        if type(config.leaf_policy_first_trick) is not bool:
            raise PVSearchPolicyError("leaf_policy_first_trick must be a bool")
        if config.leaf_policy_first_trick:
            if not config.value_declare and self._leaf_bury_arm not in BURY_MODEL_ARMS:
                raise PVSearchPolicyError(_LEAF_POLICY_NO_EFFECT)
            self.leaf_policy_first_trick = True
        if type(config.oracle_worlds) is not bool:
            raise PVSearchPolicyError("oracle_worlds must be a bool")
        if config.oracle_worlds:
            if config.adaptive_worlds or config.adaptive_worlds_leads:
                raise PVSearchPolicyError(_ORACLE_ADAPTIVE_EXCLUSIVE)
            # instance state only when on; the hook stays unbound until the
            # screen harness binds it (`bind_oracle_deal`)
            self.oracle_worlds = True
        mix_k, pin_q = _check_soft_oracle(config)
        if mix_k:
            # instance state only when on, as ``oracle_worlds``
            self.oracle_mix_k = mix_k
        if pin_q:
            self.oracle_pin_q = pin_q
        if mix_k or pin_q:
            self.soft_oracle_counts = dict.fromkeys(SOFT_ORACLE_COUNTERS, 0)
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

    # -- the diagnostic oracle's harness hook (module docstring, #707 S16) -----

    def bind_oracle_deal(self, source) -> None:
        """Install the screen harness's true-deal hook: ``source(rnd, seat)``
        returns ``(hands, buried)``, the four hands as dealt (this seat's
        included) and the kitty, for the round the harness owns.  The ONLY way
        the true hands reach this bot.  Refused on a bot whose rule is off (a
        hook with no rule would be a served bot carrying hidden information)."""
        if not self._oracle_on():
            raise PVSearchPolicyError(_ORACLE_HOOK_WITHOUT_RULE)
        if not callable(source):
            raise PVSearchPolicyError("the oracle_deal hook must be callable")
        self._oracle_deal = source

    def _oracle_on(self) -> bool:
        """Any oracle diagnostic: ``oracle_worlds`` or a soft variant."""
        return bool(self.oracle_worlds or self.oracle_mix_k or self.oracle_pin_q)

    def _require_oracle_bound(self):
        if self._oracle_on() and self._oracle_deal is None:
            raise OracleWorldsError("an oracle diagnostic is on but no harness hook is bound "
                                    "(PVSearchBot.bind_oracle_deal); refusing to play",
                                    stage="oracle_worlds_unbound")

    def _oracle_world(self, rnd, seat, mem):
        """The one true world through production's world contract: the hook's
        deal is validated exactly as a sampled world is
        (`MCBot._complete_determinized_hands`: the other seats' sizes, card
        conservation against the deck) and canonicalised the same way."""
        self._require_oracle_bound()
        try:
            hands, buried = self._oracle_deal(rnd, seat)
            hands = [list(hand) for hand in hands]
            buried = sorted(buried)
        except OracleWorldsError:
            raise
        except Exception as exc:
            raise OracleWorldsError(f"the oracle_deal hook failed: {type(exc).__name__}: {exc}",
                                    stage="oracle_worlds_hook") from exc
        if len(hands) != 4:
            raise OracleWorldsError("the oracle deal must carry four hands",
                                    stage="oracle_worlds_contract")
        if Counter(hands[seat]) != Counter(rnd.hands[seat]):
            raise OracleWorldsError("the oracle deal's hand for this seat is not this seat's hand",
                                    stage="oracle_worlds_contract")
        try:
            complete = self.sampler._complete_determinized_hands(
                rnd, seat, {s: hands[s] for s in range(4) if s != seat}, buried=buried)
        except Exception as exc:
            raise OracleWorldsError(f"the oracle deal violates the world contract: {exc}",
                                    stage="oracle_worlds_contract") from exc
        return [(complete, buried)], 1

    def _production_draw(self, rnd, seat, n, refusals, mem, check_budget, stats):
        """``n`` worlds by production's own path (refusal-aware when the round
        has a refusal); its refusal counters are added into ``stats``."""
        if refusals:
            worlds, attempts, sampled = sample_worlds_refusal_aware(
                self.sampler, rnd, seat, n, refusals, mem=mem, check_budget=check_budget)
            for key in ("refusal_rejections", "refusal_fallback_worlds", "refusal_pinned_codes"):
                stats[key] = stats.get(key, 0) + sampled[key]
            stats["refusal_observations"] = sampled["refusal_observations"]
            return worlds, attempts
        return sample_worlds(self.sampler, rnd, seat, n, mem=mem, check_budget=check_budget)

    def _soft_oracle_worlds(self, rnd, seat, mem, refusals, check_budget):
        """The soft oracle (module docstring, `pv_soft_oracle`): W worlds, k of
        them the true deal (``oracle_mix_k``) or each with a fraction q of the
        hidden copies pinned to the truth (``oracle_pin_q``).  Sets
        ``self._soft_oracle`` (the record's scalars) and, with refusals, the
        refusal rule's own record fields."""
        [(true_hands, true_buried)], _ = self._oracle_world(rnd, seat, mem)
        if any(rnd.ordering.eff_suit(c) in mem.voids[s]
               for s in range(4) if s != seat for c in true_hands[s]):
            raise OracleWorldsError("the true deal violates an inferred public void",
                                    stage="oracle_worlds_void_check")
        stats = {}
        if refusals:
            from ..ai.refusal import pin_unplayed_attempt
            # production's refusal pins, before the layout reads `mem.known`
            stats = {"refusal_observations": len(refusals), "refusal_rejections": 0,
                     "refusal_fallback_worlds": 0,
                     "refusal_pinned_codes": sum(pin_unplayed_attempt(mem, rnd, r, seat)
                                                 for r in refusals)}
        try:
            layout = soft_oracle.hidden_layout(self.sampler, rnd, seat, mem, true_hands,
                                               true_buried)
        except ValueError as exc:
            raise OracleWorldsError(f"the oracle deal does not fit the sampler's pool: {exc}",
                                    stage="oracle_worlds_contract") from exc
        truth = (true_hands, list(true_buried))
        pinned_total = fallback = fills = rejected = 0
        counts = self.soft_oracle_counts
        counts["constructions"] += 1
        # the indices of production-drawn worlds (k-mix: the non-true ones;
        # q-pin: the fallbacks); instance state of an ON bot only, not recorded
        self._soft_oracle_drawn_at = []
        if self.oracle_mix_k:
            k = self.oracle_mix_k
            counts["production_worlds"] += self.worlds - k
            drawn, attempts = self._production_draw(rnd, seat, self.worlds - k, refusals, mem,
                                                    check_budget, stats)
            if len(drawn) != self.worlds - k:
                raise PVSearchPolicyError(
                    f"policy world sampling short: {len(drawn)}/{self.worlds - k}",
                    stage="world_sampling_short")
            positions = set(soft_oracle.mix_positions(k, self.worlds))
            drawn = iter(drawn)
            worlds = [([list(h) for h in truth[0]], list(truth[1])) if i in positions
                      else next(drawn) for i in range(self.worlds)]
            self._soft_oracle_drawn_at = [i for i in range(self.worlds) if i not in positions]
            counts["true_worlds"] += k
        else:
            q = self.oracle_pin_q
            worlds, attempts = [], 0
            want = soft_oracle.pin_count(q, layout.hidden)
            for _ in range(self.worlds):
                if check_budget is not None:
                    check_budget()
                rng = soft_oracle.pin_rng(self.sampler)
                pins = [layout.truth[i] for i in sorted(rng.sample(range(layout.hidden), want))]
                world = None
                for _attempt in range(soft_oracle.PIN_FILL_ATTEMPTS):
                    attempts += 1
                    fills += 1
                    counts["pin_fills"] += 1
                    got = soft_oracle.pinned_fill(self.sampler, rnd, mem, layout, pins)
                    if got is None:
                        counts["pin_fill_failed"] += 1
                        continue
                    hands, kitty = got
                    complete = self.sampler._complete_determinized_hands(rnd, seat, hands,
                                                                         buried=kitty)
                    if soft_oracle.world_violations(rnd, seat, mem, layout, complete, kitty,
                                                    refusals):
                        rejected += 1
                        counts["pin_rejections"] += 1
                        continue
                    world = (complete, sorted(kitty))
                    break
                if world is None:
                    # production's draw for this world, counted (once, here:
                    # the draw itself is production's sampler work)
                    counts["pin_fallback_worlds"] += 1
                    extra, more = self._production_draw(rnd, seat, 1, refusals, mem,
                                                        check_budget, stats)
                    attempts += more
                    fallback += 1
                    self._soft_oracle_drawn_at.extend(range(len(worlds), len(worlds) + len(extra)))
                    worlds.extend(extra)
                    continue
                pinned_total += want
                counts["pin_worlds"] += 1
                counts["pinned_copies"] += want
                worlds.append(world)
        matched = exact = 0
        for hands, buried in worlds:
            m, e = soft_oracle.agreement(layout, hands, buried)
            matched += m
            exact += e
        n = len(worlds)
        hidden = layout.hidden
        counts["constructions_complete"] += 1
        self._soft_oracle = {
            "oracle_mix_k": int(self.oracle_mix_k), "oracle_pin_q": float(self.oracle_pin_q),
            "oracle_hidden_copies": hidden,
            "oracle_true_worlds": int(exact),
            "oracle_card_agreement": (matched / (hidden * n)) if hidden and n else 1.0,
            "oracle_pinned_copies": int(pinned_total),
            "oracle_pin_fraction": (pinned_total / (hidden * n)) if hidden and n else None,
            "oracle_pin_fallback_worlds": int(fallback),
            "oracle_pin_fills": int(fills),
            "oracle_pin_rejections": int(rejected),
        }
        return worlds, attempts, stats

    def _soft_oracle_record(self):
        """The soft oracle's scalar record fields: present only while it is on
        (scalars only, so the screen trace keeps every one: `trace_fields`)."""
        if not (self.oracle_mix_k or self.oracle_pin_q) or self._soft_oracle is None:
            return {}
        return dict(self._soft_oracle)

    # -- the optional declaration rule (module docstring) -----------------------

    def _declare_gate_name(self, rnd, seat, final, heuristic):
        """Why ``value_declare`` admits this chance (one of `VALUE_DECLARE_GATES`),
        or None: the single definition of the gate.  ``final`` and a heuristic
        declaration keep their names under ``value_declare_every_first``, which
        adds only ``"every_first"``: a first-round chance with an option the
        plain gate would have skipped."""
        if not self.value_declare or not rnd.declare_options(seat):
            return None
        if final:
            return "final"
        if heuristic is not None:
            return "heuristic"
        if self.value_declare_every_first and rnd.banker is None:
            return "every_first"
        return None

    def declare_gate(self, rnd, seat, final=False):
        """Cheap, read-only serving gate; no model admission or snapshot needed.
        ``(heuristic choice, admitted)``: the server copies the room and runs
        `decide_declare` off-loop only when ``admitted``."""
        heuristic = super().decide_declare(rnd, seat, final)
        return heuristic, self._declare_gate_name(rnd, seat, final, heuristic) is not None

    def decide_declare(self, rnd, seat, final=False, *, check_budget=None):
        """The heuristic's declaration, or under ``value_declare`` the value head's,
        or under ``declare_asap_first`` the model-free first-round rule's.

        Off: exactly `HeuristicBot.decide_declare` (no record, no attribute set).

        ``declare_asap_first`` (module docstring; exclusive with
        ``value_declare``): `_asap_declare_decision`, no model call, no budget.

        On: the heuristic's choice is computed FIRST and is the base decision.
        Gate: the value evaluation runs only when the seat has declare options
        AND either ``final`` (the grace window, where the heuristic's lower bar
        and its last word are) or the heuristic would declare now; every other
        call (most dealt cards) returns the heuristic's None unchanged with
        ``last_declare_record`` None.  This bounds the cost to the moments a
        declaration is actually on the table, and means the rule can withhold,
        redirect (another suit / NT) or -- only in the grace window -- add a
        declaration, but never fires a mid-deal declaration the heuristic would
        not have made.
        Evaluation: each distinct outcome (`value_declare.candidate_outcomes`:
        every option and PASS, merged when they reach the same banker and trump)
        is scored on the SAME ``value_declare_worlds`` sampled deals
        (`value_declare` world model; a per-decision RNG, so no bot stream
        moves); the mean is the value head's expected signed level for the
        seat's team.  The argmax (lowest candidate position on a tie, the
        heuristic's outcome first) replaces the heuristic's choice only when its
        mean exceeds the heuristic outcome's by MORE than
        ``value_declare_margin``.
        Budget: optional caller ``check_budget`` is a cooperative per-call
        deadline/cancellation guard, composed with (never replacing) the bot's
        serving budget. Raise ``PVSearchBudgetExceeded`` for heuristic fallback;
        ``BaseException`` cancellation propagates. Omitting the caller guard
        preserves the existing recipe and budget. This does not move work off-loop or
        interrupt an in-flight evaluator batch.
        The evaluation is one `OptionalStage` after the finalized base;
        with a serving budget every bounded step (each world, each value batch)
        passes the stage's latching guard and the replacement is published only
        after the final hard check.  An expiry -- also one a nested step
        swallowed -- or any ``Exception`` abandons it: the heuristic's choice is
        returned and the record says why.  ``BaseException`` propagates.
        Record (``last_declare_record``, schema ``pv-value-declare-decision-v1``;
        cards as space-joined strings, PASS as ``"PASS"``): ``evaluated`` (the
        evaluation completed), ``heuristic``, ``value_choice`` (the argmax),
        ``played`` (returned), ``changed`` (played != heuristic), ``worlds``,
        ``worlds_completed``, ``fallback_reason`` (None / ``hard_budget`` /
        ``error``), ``fallback_error``, ``outcomes``, ``outcome_means``,
        ``heuristic_mean``, ``best_mean``, ``margin``, ``final``, ``seconds``,
        ``gate`` (why the chance was admitted: `VALUE_DECLARE_GATES`; under
        ``value_declare_every_first`` only the gate changes).
        """
        heuristic = super().decide_declare(rnd, seat, final)
        if self.declare_asap_first:
            return self._asap_declare_decision(rnd, seat, final, heuristic)
        if not self.value_declare:
            return heuristic
        started = time.perf_counter()
        self.last_declare_record = None
        gate = self._declare_gate_name(rnd, seat, final, heuristic)
        if gate is None:
            return heuristic
        options = rnd.declare_options(seat)
        budget = self.serving_budget_seconds
        caller_check = check_budget
        check_budget = None
        if budget is not None or caller_check is not None:
            def check_budget():
                if budget is not None and time.perf_counter() - started >= budget:
                    raise PVSearchBudgetExceeded("pv-search serving budget expired")
                if caller_check is not None:
                    caller_check()
        return self._value_declare_decision(rnd, seat, final, heuristic, options, started,
                                            check_budget, gate=gate)

    def _asap_declare_decision(self, rnd, seat, final, heuristic):
        """``declare_asap_first`` (module docstring): in a first round, the
        strongest available option at every chance that has one; with a fixed
        banker, the heuristic's choice.  Sets ``last_declare_record``
        (``pv-declare-asap-decision-v1``) when it declares, else None."""
        self.last_declare_record = None
        if rnd.banker is not None:
            return heuristic
        options = rnd.declare_options(seat)
        if not options:
            return None
        hand = rnd.hands[seat]
        suit_length = Counter(card_suit(c) for c in hand if not is_joker(c))

        def preference(indexed):
            index, option = indexed
            code = option[0]
            held = 0 if is_joker(code) else suit_length[card_suit(code)]
            return (rnd._declaration_strength(option), held, -index)
        _, chosen = max(enumerate(options), key=preference)
        current = rnd.declaration
        self.last_declare_record = {
            "schema": DECLARE_ASAP_RECORD_SCHEMA, "policy": getattr(self, "policy_name", None),
            "seat": int(seat), "final": bool(final),
            "cards_dealt": sum(len(h) for h in rnd.hands),
            "options": len(options),
            "chosen": " ".join(chosen),
            "strength": int(rnd._declaration_strength(chosen)),
            "overcall": current is not None,
            "overcall_self": current is not None and current["seat"] == seat,
            "heuristic": value_declare_model.PASS if heuristic is None else " ".join(heuristic),
        }
        return list(chosen)

    def _value_declare_decision(self, rnd, seat, final, heuristic, options, started,
                                check_budget, gate=None):
        """The gated decision (`decide_declare`): the optional stage over the
        finalized ``heuristic`` base, under ``check_budget`` (None: no budget).
        ``gate`` is the record's admission name (None: the plain gate's)."""
        if gate is None:
            gate = "final" if final else "heuristic"
        outcomes = value_declare_model.candidate_outcomes(rnd, seat, options, heuristic)
        progress = {"worlds_completed": 0,
                    "leaf_first_trick": "policy" if self.leaf_policy_first_trick else "heuristic",
                    "leaf_first_trick_fallbacks": 0}
        if self.value_declare_pass_worlds:
            # only with the rule on: the sampler's acceptance counts
            progress["pass_worlds"] = {"hazard": declare_pass_worlds.HAZARD,
                                       "max_attempts": declare_pass_worlds.MAX_ATTEMPTS,
                                       "worlds": 0, "attempts": 0, "fallbacks": 0}
        stage = OptionalStage(self, (), hard_check=check_budget,
                              budget_errors=PVSearchBudgetExceeded, abandon_on=Exception)
        means = best = None
        decided = None      # the means the argmax and margin used (``vdsb``: adjusted)
        served = None       # the ``vdsb`` record, only with the rule on
        with stage:
            means = self._value_declare_means(rnd, seat, [option for _, option in outcomes],
                                              check_budget=stage.guard, progress=progress)
            best = max(range(len(outcomes)), key=lambda i: (float(means[i]), -i))
            decided = means
            if self.value_declare_served_bury:
                served = {"ordinary_choice": None}
                best, decided = self._served_bury_pass(rnd, seat, outcomes, means,
                                                       stage.guard, served)
            switch = bool(decided[best] - decided[0] > self.value_declare_margin)
            played = outcomes[best][1] if switch else heuristic
            stage.publish(changed=switch)
        if stage.abandoned:
            played, best, means, decided = heuristic, None, None, None
        wait = None         # the ``vdw`` record, only with the rule on
        if (self.value_declare_wait and not final and not stage.abandoned
                and played is not None):
            played, wait = self._declare_wait_decision(rnd, seat, played, check_budget)

        def cards(option):
            return value_declare_model.PASS if option is None else " ".join(option)
        record = {
            "schema": VALUE_DECLARE_RECORD_SCHEMA, "policy": getattr(self, "policy_name", None),
            "seat": int(seat), "final": bool(final),
            "cards_dealt": sum(len(h) for h in rnd.hands),
            "evaluated": not stage.abandoned,
            "heuristic": cards(heuristic),
            "value_choice": None if best is None else cards(outcomes[best][1]),
            "played": cards(played),
            "changed": cards(played) != cards(heuristic),
            "worlds": self.value_declare_worlds,
            "worlds_completed": progress["worlds_completed"],
            "fallback_reason": stage.reason, "fallback_error": stage.error,
            "outcomes": " | ".join(f"{b}:{t}={cards(o)}" for (b, t), o in outcomes),
            "outcome_means": None if means is None else [float(m) for m in means],
            "heuristic_mean": None if decided is None else float(decided[0]),
            "best_mean": None if decided is None else float(decided[best]),
            "margin": self.value_declare_margin,
            "seconds": time.perf_counter() - started,
            "gate": gate,
            # who played the leaves' first trick (`leaf_policy_first_trick`) and
            # how many seats the policy player handed to the heuristic
            "leaf_first_trick": progress["leaf_first_trick"],
            "leaf_first_trick_fallbacks": progress["leaf_first_trick_fallbacks"],
        }
        if self.value_declare_served_bury:
            # only with the rule on: a flag-off record's key set is unchanged
            record["served_bury"] = served
        if self.value_declare_pass_worlds:
            # only with the rule on: a flag-off record's key set is unchanged
            record["pass_worlds"] = dict(progress["pass_worlds"])
        if self.value_declare_wait:
            # likewise; None where the wait pass did not run (the grace window,
            # an abandoned evaluation, or a value choice that already passes)
            record["wait"] = wait
        self.last_declare_record = record
        return None if played is None else list(played)

    def _served_bury_pass(self, rnd, seat, outcomes, means, check_budget, record):
        """``value_declare_served_bury`` (module docstring, `declare_served_bury`):
        ``(best, decided)``, the outcome index the margin test compares with the
        heuristic's (0) and the means it compares, filling ``record``.

        The ordinary pass's ``means`` (heuristic bury, ``value_declare_worlds``
        worlds) nominate ONE challenger: the best outcome other than the
        heuristic's (lowest position on a tie).  The heuristic's outcome and the
        challenger are then scored on the first ``WORLDS_DEFAULT`` worlds of the
        same per-decision stream, each twice per world -- with the heuristic
        bury and with the served chooser's (`declare_served_bury.served_bury`) --
        and each mean is the control-variate estimate ``ordinary mean +
        (served-bury mean - heuristic-bury mean)`` over those paired worlds.
        Only those two compete; with a single outcome nothing is re-scored."""
        started = time.perf_counter()

        def cards(option):
            return value_declare_model.PASS if option is None else " ".join(option)
        ordinary_best = max(range(len(outcomes)), key=lambda i: (float(means[i]), -i))
        record.update(ordinary_choice=cards(outcomes[ordinary_best][1]),
                      challenger=None, k=declare_served_bury.K_DEFAULT,
                      model_worlds=declare_served_bury.MODEL_WORLDS_DEFAULT,
                      worlds=declare_served_bury.WORLDS_DEFAULT, worlds_completed=0,
                      heuristic_bury_means=None, served_bury_means=None,
                      adjusted_means=None, seconds=0.0)
        if len(outcomes) < 2:
            record["seconds"] = time.perf_counter() - started
            return ordinary_best, means
        challenger = max(range(1, len(outcomes)), key=lambda i: (float(means[i]), -i))
        record["challenger"] = cards(outcomes[challenger][1])

        def bury(world, banker):
            return declare_served_bury.served_bury(
                self, world, banker, k=declare_served_bury.K_DEFAULT,
                model_worlds=declare_served_bury.MODEL_WORLDS_DEFAULT,
                check_budget=check_budget)
        pair = [outcomes[0][1], outcomes[challenger][1]]
        progress = {"worlds_completed": 0, "leaf_first_trick_fallbacks": 0}
        twin = self._value_declare_means(rnd, seat, pair + pair, check_budget=check_budget,
                                         progress=progress,
                                         worlds=declare_served_bury.WORLDS_DEFAULT,
                                         buries=[None, None, bury, bury])
        record["worlds_completed"] = progress["worlds_completed"]
        heuristic_bury, served_bury = twin[:2], twin[2:]
        adjusted = [float(means[0]) + float(served_bury[0] - heuristic_bury[0]),
                    float(means[challenger]) + float(served_bury[1] - heuristic_bury[1])]
        record.update(heuristic_bury_means=[float(v) for v in heuristic_bury],
                      served_bury_means=[float(v) for v in served_bury],
                      adjusted_means=adjusted)
        decided = np.full(len(outcomes), -np.inf)
        decided[0], decided[challenger] = adjusted
        best = challenger if adjusted[1] > adjusted[0] else 0
        record["seconds"] = time.perf_counter() - started
        return best, decided

    def _declare_wait_decision(self, rnd, seat, now, check_budget):
        """``value_declare_wait`` (module docstring, `declare_wait`): ``(played,
        record)`` after the value declaration chose to declare ``now`` at a
        chance during the deal.  One `OptionalStage` over that FINALIZED
        choice: `_declare_wait_values` scores NOW and WAIT on the same worlds,
        and the bot waits (``played`` None) only when WAIT's mean beats NOW's by
        more than ``value_declare_margin``.  An expiry or any ``Exception``
        abandons the stage to ``now`` (the value declaration's choice, NOT the
        heuristic's) and the record says why; ``BaseException`` propagates."""
        started = time.perf_counter()
        progress = {"draws": 0, "worlds_accepted": 0, "worlds_completed": 0,
                    "same_outcome_worlds": 0,
                    "now_still_legal_worlds": 0, "wait_end_declares": 0,
                    "end_choices_scored": 0, "leaf_first_trick_fallbacks": 0}
        stage = OptionalStage(self, (), hard_check=check_budget,
                              budget_errors=PVSearchBudgetExceeded, abandon_on=Exception)
        means = None
        waited = False
        with stage:
            means = self._declare_wait_values(rnd, seat, now, check_budget=stage.guard,
                                              progress=progress)
            waited = bool(means[1] - means[0] > self.value_declare_margin)
            stage.publish(changed=waited)
        if stage.abandoned:
            means, waited = None, False
        record = {
            "evaluated": not stage.abandoned,
            "now": " ".join(now),
            "waited": waited,
            "now_mean": None if means is None else float(means[0]),
            "wait_mean": None if means is None else float(means[1]),
            "worlds": declare_wait.WORLDS_DEFAULT,
            "inner_worlds": declare_wait.INNER_WORLDS_DEFAULT,
            "draws_cap": declare_wait.DRAWS_CAP,
            **progress,
            "fallback_reason": stage.reason, "fallback_error": stage.error,
            "seconds": time.perf_counter() - started,
        }
        return (None if waited else now), record

    def _score_declare_positions(self, positions, seat, leaf, check_budget):
        """Value-head scores of ``positions`` from ``seat``'s team, in batches
        of at most ``batch_size`` (the leaf's first trick played on each batch
        under ``leaf_policy_first_trick``); ``check_budget`` around every batch."""
        values = []
        for start in range(0, len(positions), self.batch_size):
            batch = positions[start:start + self.batch_size]
            if check_budget is not None:
                check_budget()
            if leaf is not None:
                leaf.play_first_tricks(batch)
            scores = np.asarray(self.evaluator.score(list(batch), seat), dtype=np.float64)
            if scores.shape != (len(batch),) or not np.isfinite(scores).all():
                raise ValueError("value evaluator requires one finite root-team score per position")
            values.append(scores)
        if check_budget is not None:
            check_budget()
        return np.concatenate(values) if values else np.zeros(0, dtype=np.float64)

    def _declare_wait_end_choice(self, sim, seat, rng, leaf, check_budget):
        """The decider's one end-of-deal decision on the played-out ``sim``
        (`declare_wait`): its distinct outcomes (PASS first), the argmax of the
        value head's mean over `INNER_WORLDS_DEFAULT` worlds sampled from its
        OWN end-of-deal view (lowest position on a tie).  ``(option, scored)``:
        a single outcome needs no scoring."""
        outcomes = declare_wait.end_candidates(sim, seat)
        if len(outcomes) == 1:
            return outcomes[0][1], False
        positions = []
        for _ in range(declare_wait.INNER_WORLDS_DEFAULT):
            if check_budget is not None:
                check_budget()
            hands, kitty = value_declare_model.sample_declare_world(sim, seat, rng)
            for _, option in outcomes:
                positions.append(value_declare_model.declare_outcome_position(
                    sim, seat, hands, kitty, option, first_trick=leaf is None))
        scores = self._score_declare_positions(positions, seat, leaf, check_budget)
        means = scores.reshape(declare_wait.INNER_WORLDS_DEFAULT, len(outcomes)).mean(axis=0)
        best = max(range(len(outcomes)), key=lambda i: (float(means[i]), -i))
        return outcomes[best][1], True

    def _declare_wait_values(self, rnd, seat, now, check_budget=None, progress=None):
        """``[NOW mean, WAIT mean]`` (`declare_wait`, module docstring): on the
        first `WORLDS_DEFAULT` draws of the ordinary pass's per-decision stream
        that pass `declare_wait.silence_consistent` (at most `DRAWS_CAP` draws;
        none accepted raises, which abandons the stage), both branches play out the rest of the deal (the other seats by
        the heuristic declare policy, the decider silent), the decider makes its
        end-of-deal choice from its own view (`_declare_wait_end_choice`, the
        same inner stream for both branches), and each branch's chosen outcome
        is scored in the outer world.  A world whose branches end on the same
        outcome is scored once and counts for both (difference exactly 0).
        ``check_budget`` runs before every world and around every batch."""
        rng = value_declare_model.decision_rng(self.seed, rnd, seat)
        leaf = self._policy_first_trick(value_declare_model.default_finisher(), check_budget)
        progress = {} if progress is None else progress
        sums = np.zeros(2, dtype=np.float64)
        pending, owners, worlds_pending = [], [], 0

        def flush():
            nonlocal worlds_pending
            if not pending:
                return
            scores = self._score_declare_positions(pending, seat, leaf, check_budget)
            for value, branches in zip(scores, owners):
                for branch in branches:
                    sums[branch] += value
            progress["worlds_completed"] = progress.get("worlds_completed", 0) + worlds_pending
            worlds_pending = 0
            pending.clear()
            owners.clear()

        accepted = draws = 0
        while accepted < declare_wait.WORLDS_DEFAULT and draws < declare_wait.DRAWS_CAP:
            if check_budget is not None:
                check_budget()
            hands, kitty = value_declare_model.sample_declare_world(rnd, seat, rng)
            draws += 1
            progress["draws"] = draws
            if not declare_wait.silence_consistent(
                    declare_wait.continuation_round(rnd, seat, hands, kitty), seat):
                continue
            world = accepted
            accepted += 1
            progress["worlds_accepted"] = accepted
            ends = []
            for declare_now in (True, False):
                sim = declare_wait.continuation_round(rnd, seat, hands, kitty)
                if declare_now:
                    sim.declare(seat, list(now))
                declare_wait.play_out_deal(sim, seat)
                choice, scored = self._declare_wait_end_choice(
                    sim, seat, declare_wait.inner_rng(self.seed, rnd, seat, world), leaf,
                    check_budget)
                progress["end_choices_scored"] = progress.get("end_choices_scored", 0) + scored
                ends.append((sim, choice, value_declare_model.outcome_key(sim, seat, choice)))
            (now_sim, now_choice, now_key), (wait_sim, wait_choice, wait_key) = ends
            if any(sorted(option) == sorted(now) for option in wait_sim.declare_options(seat)):
                progress["now_still_legal_worlds"] = progress.get("now_still_legal_worlds", 0) + 1
            if wait_choice is not None:
                progress["wait_end_declares"] = progress.get("wait_end_declares", 0) + 1
            if now_key == wait_key:
                progress["same_outcome_worlds"] = progress.get("same_outcome_worlds", 0) + 1
                pending.append(value_declare_model.declare_outcome_position(
                    now_sim, seat, hands, kitty, now_choice, first_trick=leaf is None))
                owners.append((0, 1))
            else:
                for branch, (sim, choice, _) in enumerate(ends):
                    pending.append(value_declare_model.declare_outcome_position(
                        sim, seat, hands, kitty, choice, first_trick=leaf is None))
                    owners.append((branch,))
            worlds_pending += 1
            if len(pending) >= self.batch_size:
                flush()
        flush()
        if leaf is not None:
            progress["leaf_first_trick_fallbacks"] = int(leaf.fallbacks)
        if accepted == 0:
            raise value_declare_model.ValueDeclareError(
                "no sampled world is consistent with the other seats' silence")
        return sums / accepted

    def _policy_first_trick(self, fallback, check_budget=None):
        """The ``leaf_policy_first_trick`` player on this bot's own policy prior
        and encoder version (module docstring), or None while the rule is off."""
        if not self.leaf_policy_first_trick:
            return None
        return PolicyFirstTrick(self.predict, self.version, fallback, check_budget=check_budget)

    def _value_declare_means(self, rnd, seat, candidates, check_budget=None, progress=None,
                             worlds=None, buries=None):
        """Mean value-head score per candidate (None = PASS) over
        ``value_declare_worlds`` sampled deals (``worlds``: the first that many
        of the same stream), world-major, in value batches of at most
        ``batch_size`` that end on a world boundary; ``check_budget`` runs
        before every world and around every batch.  ``buries`` (one per
        candidate; None = the heuristic's) is the bury each candidate's world
        banker makes (`value_declare.declare_outcome_position`).  Under
        ``value_declare_pass_worlds`` each world is the pass-conditioned draw
        (`declare_pass_worlds.sample_pass_world`, counted in
        ``progress["pass_worlds"]`` when the caller passes it) from the same
        per-decision stream."""
        worlds = self.value_declare_worlds if worlds is None else worlds
        rng = value_declare_model.decision_rng(self.seed, rnd, seat)
        pass_stats = None if progress is None else progress.get("pass_worlds")
        sums = np.zeros(len(candidates), dtype=np.float64)
        pending, indices, worlds_pending = [], [], 0
        # the leaf's first trick: the heuristic's inside `declare_outcome_position`,
        # or (``leaf_policy_first_trick``) the policy head's on each batch
        leaf = self._policy_first_trick(value_declare_model.default_finisher(), check_budget)

        def flush():
            nonlocal worlds_pending
            if not pending:
                return
            if check_budget is not None:
                check_budget()
            if leaf is not None:
                try:
                    leaf.play_first_tricks(pending)
                finally:
                    if progress is not None:
                        progress["leaf_first_trick_fallbacks"] = int(leaf.fallbacks)
            scores = np.asarray(self.evaluator.score(list(pending), seat), dtype=np.float64)
            if scores.shape != (len(pending),) or not np.isfinite(scores).all():
                raise ValueError("value evaluator requires one finite root-team score per position")
            np.add.at(sums, indices, scores)
            if progress is not None:
                progress["worlds_completed"] += worlds_pending
            worlds_pending = 0
            pending.clear()
            indices.clear()
            if check_budget is not None:
                check_budget()

        for _ in range(worlds):
            if check_budget is not None:
                check_budget()
            if self.value_declare_pass_worlds:
                hands, kitty = declare_pass_worlds.sample_pass_world(rnd, seat, rng, pass_stats)
            else:
                hands, kitty = value_declare_model.sample_declare_world(rnd, seat, rng)
            for index, option in enumerate(candidates):
                pending.append(value_declare_model.declare_outcome_position(
                    rnd, seat, hands, kitty, option, first_trick=leaf is None,
                    bury=None if buries is None else buries[index]))
                indices.append(index)
            worlds_pending += 1
            if len(pending) >= self.batch_size:
                flush()
        flush()
        return sums / worlds

    # -- the two harness hooks that serving changes -------------------------

    def scores(self, rnd, seat, actions, worlds):
        """As the harness, with the package's encoder version threaded through."""
        # lazy: policy_prior -> harvest.rebuild -> registry -> (env registration) -> this module
        # is a cycle when the rows extractor is imported first with SHENGJI_PV_* set
        from .policy_prior import CARD_INDEX, N_CARDS, flat_input, root_tensors
        if self.encode_prefix_cache:
            # the same rows, the public block encoded once (`pv_encode_prefix`)
            from .pv_encode_prefix import prior_rows
            x = prior_rows(rnd, seat, worlds, self.version)
        else:
            x = np.stack([flat_input(root_tensors(root_clone(rnd, hands, buried), seat,
                                                  self.version), self.version)
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
        if self.oracle_worlds:
            # the diagnostic (module docstring): one world, the true deal from the
            # harness hook; no draw, the sampler's stream untouched, the refusal
            # ledger observed above as always (its record stays zero: nothing to
            # constrain); the void check below applies to it as to any world
            worlds, attempts = self._oracle_world(rnd, seat, mem)
        elif self.oracle_mix_k or self.oracle_pin_q:
            # its soft variants (module docstring): W worlds, partly true
            self._soft_oracle = None
            worlds, attempts, self._last_sampling = self._soft_oracle_worlds(
                rnd, seat, mem, refusals, check_budget)
        elif getattr(self, "world_history_legal", False) and getattr(self, "belief_worlds", False):
            worlds, attempts, self._last_sampling = self._belief_worlds(
                rnd, seat, mem, refusals, check_budget)
        elif getattr(self, "world_history_legal", False):
            # getattr: a bot built without __init__ (a bare test double or an
            # older snapshot) has the rule off
            worlds, attempts, self._last_sampling = sample_worlds_history_legal(
                self.sampler, rnd, seat, self.worlds, refusals, mem=mem,
                check_budget=check_budget,
                constrain=getattr(self, "world_history_draw", False))
        elif refusals:
            worlds, attempts, self._last_sampling = sample_worlds_refusal_aware(
                self.sampler, rnd, seat, self.worlds, refusals, mem=mem,
                check_budget=check_budget)
        else:
            # the rule off, or on with no refusal this round: production's draw,
            # unchanged (the same stream, the same worlds for the same seed)
            worlds, attempts = sample_worlds(self.sampler, rnd, seat, self.worlds, mem=mem,
                                             check_budget=check_budget)
        expected = 1 if self.oracle_worlds else self.worlds
        if len(worlds) != expected:
            raise PVSearchPolicyError(f"policy world sampling short: {len(worlds)}/{expected}",
                                      stage="world_sampling_short")
        if any(rnd.ordering.eff_suit(c) in mem.voids[s]
               for hands, _ in worlds for s in range(4) if s != seat for c in hands[s]):
            if self.oracle_worlds:
                # the TRUE deal contradicts an inferred void: a memory defect,
                # never a sampling accident; the diagnostic fails closed
                raise OracleWorldsError("the true deal violates an inferred public void",
                                        stage="oracle_worlds_void_check")
            raise PVSearchPolicyError("policy world sampling violates public voids",
                                      stage="world_sampling_void_check")
        return worlds, attempts

    def _belief_worlds(self, rnd, seat, mem, refusals, check_budget):
        """The history-legal draw with the S17 belief proposal as its source
        (`ai.belief_numpy.BeliefProposal`).  Any error other than the serving
        budget -- no package, a featurizer or model failure, a preparation over
        ``BELIEF_PREP_SECONDS``, an infeasible state -- falls back to the
        history-legal production draw for this decision, recorded as
        ``belief_fallback`` with the error's type."""
        from ..ai.belief_numpy import BeliefNumpyError, BeliefProposal, log_fields
        t0 = time.perf_counter()
        seed = None
        try:
            if check_budget is not None:
                check_budget()
            if self.belief_model is None:
                raise BeliefNumpyError("no belief package bound")
            # the draw-time constraints the history-legal draw would apply: a
            # proposal bypasses them there, so it honours them itself
            constraints = draw_constraints(rnd, seat)
            seed = self.sampler.rng.getrandbits(63)
            fast = self.world_fast
            propose = BeliefProposal(self.belief_model, rnd, seat, refusals,
                                     seed=seed, batch=self.worlds,
                                     forbidden=constraints, check_budget=check_budget,
                                     capacity=getattr(self, "belief_capacity", False),
                                     **({"native": True} if fast else {}))
            complete = None
            if fast:
                from .pv_native import world_completion
                complete = world_completion(self.sampler, rnd, seat)
            worlds, attempts, stats = sample_worlds_history_legal(
                self.sampler, rnd, seat, self.worlds, refusals, mem=mem,
                check_budget=check_budget, propose=propose, constrain=True,
                **({"complete": complete} if complete is not None else {}))
            stats.update(history_draw_constraints=len(constraints),
                         history_draw_forbidden=sum(sum(c.values()) for c in constraints.values()),
                         belief_fallback=0, belief_proposed=int(propose.drawn),
                         belief_ms=round(1e3 * (time.perf_counter() - t0), 3))
            if self.belief_log:
                stats.update(self._belief_log_seed(seed, refusals))
                # the log never decides: a failure here is recorded, and the
                # drawn worlds are returned as they are
                try:
                    stats.update(log_fields(propose))
                except Exception as exc:
                    stats["belief_log_error"] = type(exc).__name__
            return worlds, attempts, stats
        except (PVSearchBudgetExceeded, _AdaptiveWorldsExpired):
            raise
        except Exception as exc:
            fresh = Memory(rnd, seat, own_kitty=getattr(self.sampler, "BANKER_KITTY", True))
            worlds, attempts, stats = sample_worlds_history_legal(
                self.sampler, rnd, seat, self.worlds, refusals, mem=fresh,
                check_budget=check_budget, constrain=True)
            stats.update(belief_fallback=1, belief_proposed=0,
                         belief_ms=round(1e3 * (time.perf_counter() - t0), 3),
                         belief_error=type(exc).__name__)
            if self.belief_log and seed is not None:
                stats.update(self._belief_log_seed(seed, refusals))
            return worlds, attempts, stats

    @staticmethod
    def _belief_log_seed(seed, refusals):
        """The replay handle of a drawn proposal: its seed, and the refusal
        ledger it was built with (`ai.refusal.Refusal`) when non-empty."""
        out = {"belief_seed": int(seed)}
        if refusals:
            out["belief_refusals"] = [[int(r.seat), list(r.attempted), list(r.forced),
                                       int(r.trick_index)] for r in refusals]
        return out

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
        prefix = None
        if self.encode_prefix_cache:
            # the same tensors, the root's history traversed once (`pv_encode_prefix`)
            from .pv_encode_prefix import HistoryPrefix, score_leaves
            prefix = HistoryPrefix.of(rnd, batched=self.encode_batch_fast,
                                      native=self.encode_native)

        def flush():
            nonlocal batches
            if not pending:
                return
            if check_budget is not None:
                check_budget()
            if prefix is None:
                scores = self.evaluator.score(pending, seat)
            else:
                scores = score_leaves(self.evaluator, pending, seat, prefix)
            scores = np.asarray(scores, dtype=np.float64)
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
                pending.append(self._scored_leaf(rnd, seat, hands, buried, action, world_index))
                indices.append(index)
                if cells is not None:
                    cells.append((world_index, index))
                if len(pending) == self.batch_size:
                    flush()
        flush()
        return sums, batches

    def _scored_leaf(self, rnd, seat, hands, buried, action, world_index):
        if self._leaf_greedy_exact_skipped or self._leaf_greedy_plain_pass \
                or (self._leaf_greedy_pruned and tuple(action) in self._leaf_greedy_pruned):
            # the greedy leaf's exact-stage yield, the top-m rule's plain pass
            # and its pruned candidates (module docstring)
            return self._leaf(rnd, seat, hands, buried, action, world_index)
        return super()._scored_leaf(rnd, seat, hands, buried, action, world_index)

    def _value_means(self, rnd, seat, actions, worlds, check_budget=None):
        if self._leaf_greedy_top_applies(actions):
            sums, batches = self._leaf_greedy_top_sums(rnd, seat, actions, worlds, check_budget)
            return sums / len(worlds), batches
        if self.leaf_greedy_finish and not self._leaf_greedy_exact_skipped:
            # the optional value-leaf rule: every leaf of this pass finished at
            # once, the replies batched, under the deadline (`policy_value_search`)
            self._greedy_prefill(rnd, seat, actions, worlds, check_budget)
        sums, batches = self._score_leaves(rnd, seat, actions, worlds, check_budget)
        return sums / len(worlds), batches

    def _leaf_greedy_top_applies(self, actions):
        """``leaf_greedy_top`` restricts this pass: the greedy leaf would run and
        more than ``m`` candidates are priced."""
        return bool(self.leaf_greedy_top and self.leaf_greedy_finish
                    and not self._leaf_greedy_exact_skipped and len(actions) > self.leaf_greedy_top)

    def _leaf_greedy_top_sums(self, rnd, seat, actions, worlds, check_budget=None, capture=None):
        """``leaf_greedy_top`` (module docstring): ``(sums, batches)``, the ONE
        accumulator both the value pass (``sums / W``) and `value_matrix` return.
        Every candidate on the plain leaf, then the ``m`` best of them on the
        greedy-finished leaf; a pruned candidate's sum is its plain sum less
        ``W * LEAF_GREEDY_TOP_OFFSET``.  When the finish yields to its deadline
        every leaf is the plain one, nothing is pruned and the plain sums are
        returned: the decision is the plain decision.  ``capture`` (a W x K
        matrix) receives the same cells, offset included."""
        n = len(worlds)
        self._leaf_greedy_plain_pass = True
        try:
            plain_sums, plain_batches = self._score_leaves(rnd, seat, actions, worlds, check_budget,
                                                           capture=capture)
        finally:
            self._leaf_greedy_plain_pass = False
        plain = plain_sums / n
        order = sorted(range(len(actions)), key=lambda i: (-plain[i], i))
        kept = sorted(order[:self.leaf_greedy_top])
        kept_set = set(kept)
        pruned = [i for i in range(len(actions)) if i not in kept_set]
        self._leaf_greedy_pruned = frozenset(tuple(actions[i]) for i in pruned)
        kept_actions = [actions[i] for i in kept]
        record = {"leaf_greedy_top_applied": True, "leaf_greedy_top_kept": [int(i) for i in kept],
                  "leaf_greedy_top_plain_means": [float(v) for v in plain]}
        self._greedy_prefill(rnd, seat, kept_actions, worlds, check_budget)
        if self._leaf_greedy is not None and self._leaf_greedy["deadline_cut"]:
            # the finish passed its deadline: every leaf is plain, so is the decision
            self._leaf_greedy_pruned = frozenset()
            record.update(leaf_greedy_top_applied=False, leaf_greedy_top_kept=None)
            self._leaf_greedy_top = record
            return plain_sums, plain_batches
        sub = None if capture is None else np.full((n, len(kept)), np.nan, dtype=np.float64)
        kept_sums, batches = self._score_leaves(rnd, seat, kept_actions, worlds, check_budget,
                                                capture=sub)
        sums = plain_sums - LEAF_GREEDY_TOP_OFFSET * n
        sums[kept] = kept_sums
        if capture is not None:
            capture[:, pruned] -= LEAF_GREEDY_TOP_OFFSET
            capture[:, kept] = sub
        self._leaf_greedy_top = record
        return sums, plain_batches + batches

    def _leaf_greedy_top_record(self):
        if not self.leaf_greedy_top:
            return {}
        return dict(self._leaf_greedy_top or {"leaf_greedy_top_applied": False,
                                              "leaf_greedy_top_kept": None,
                                              "leaf_greedy_top_plain_means": None})

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
        if self._leaf_greedy_top_applies(actions):
            # the restricted pass's own accumulator: ``sums / W`` is the served means
            sums, batches = self._leaf_greedy_top_sums(rnd, seat, actions, worlds, check_budget,
                                                       capture=matrix)
        else:
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
        extra = self._finish_lead_action(rnd, seat)
        return enumerate_legal(rnd, seat, cap=self.cap,
                               must_include=list(must_include) + ([extra] if extra else []))

    def _finish_lead_action(self, rnd, seat):
        """One bounded hypothesis, not a must-play rule or a safe-throw claim.

        Price the whole hand alongside the unchanged ballot. Engine resolution
        and the normal value/selection path still decide whether it is useful.
        """
        if not self.finish_lead_admission or not leading(rnd):
            return None
        hand = rnd.hands[seat]
        if not 2 <= len(hand) <= FINISH_LEAD_MAX_CARDS:
            return None
        if len({rnd.ordering.eff_suit(c) for c in hand}) != 1:
            return None
        return sorted(hand)

    def _admit(self, rnd, seat, actions, preferences, anchor_index):
        """Indices (into ``actions``) the value head prices -- the FINAL ballot: the
        anchor first, then the policy's best scores, ``self.candidates`` in all, then
        any forced-component extras -- the harness's own admission
        (`PolicyValueBot._admit`; the worlds and the deadline reach it through the
        admission context `_search` sets).  A wrapper that captures the ballot here
        (the trajectory mixin, a hook override) captures everything the value head
        will price."""
        chosen = super()._admit(rnd, seat, actions, preferences, anchor_index)
        self._finish_lead_added = False
        finish = self._finish_lead_action(rnd, seat)
        if finish:
            for i, action in enumerate(actions):
                if sorted(action) == finish and i not in chosen and np.isfinite(preferences[i]):
                    chosen = list(chosen) + [i]
                    self._finish_lead_added = True
                    break
        return chosen

    # -- the optional lead admission width (class docstring) ----------------------

    def _admission_k(self, rnd, actions, preferences):
        """The harness's width, or under ``wide_lead_admission`` on a lead
        ``max(candidates, WIDE_LEAD_K)``; sets ``self._wide_lead`` (the record
        fields) on that lead.  Called by the harness's `_admit`, so the width
        reaches the same anchor, diversity and forced-extra code as served."""
        if not self.wide_lead_admission or not leading(rnd):
            return super()._admission_k(rnd, actions, preferences)
        k = max(self.candidates, self.wide_lead_k)
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
        if self.finish_lead_admission:
            record['finish_lead_admission_added'] = self._finish_lead_added
        if self.wide_lead_admission and self._wide_lead is not None:
            record.update(self._wide_lead)
        return record

    def _candidate_limit(self, rnd):
        """The largest admission width (``k_used``) the candidate-budget check
        accepts: the harness's bound, and ``WIDE_LEAD_K`` on a wide lead."""
        limit = max(self.candidates, self.candidates_lead_multi)
        if self.wide_lead_admission and leading(rnd):
            limit = max(limit, self.wide_lead_k)
        return limit

    def _search(self, rnd, seat, anchor, started, check_budget=None):
        if self.leaf_greedy_finish:
            self._leaf_greedy = None      # no leaf of an earlier decision is ever reused
        if self.leaf_greedy_deadline_ms:
            # measured from the decision's start, as the serving budget is
            self._leaf_greedy_deadline_at = started + self.leaf_greedy_deadline_ms / 1000.0
        if self.leaf_greedy_finish_exact_skip:
            self._leaf_greedy_exact_skipped = False
        if self.leaf_greedy_top:
            # no pruning of an earlier decision survives into this one
            self._leaf_greedy_top = None
            self._leaf_greedy_pruned = frozenset()
        single_fast = False
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
        finish_extra = int(self.finish_lead_admission and self._finish_lead_added)
        if len(budgeted) > self._adaptive["k_used"] + FORCED_EXTRA_SLOTS + finish_extra \
                or self._adaptive["k_used"] > self._candidate_limit(rnd):
            raise PVSearchPolicyError("admission exceeded the candidate budget",
                                      stage="admission_budget")
        admitted = [actions[i] for i in chosen]
        if self.leaf_greedy_finish_exact_skip:
            # decided before the value pass, from the exact stages' own gates
            self._leaf_greedy_exact_skipped = (
                (self.exact_lead_endgame and self._exact_lead_gate(rnd, admitted) is None)
                or self._exact_follow_eligible(rnd, admitted))
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
            single_fast = self._single_candidate_fast(rnd, admitted)
            if single_fast:
                # one admitted candidate: no consumer reads its value (the
                # selection of one is index 0 and no exact stage starts), so
                # the pass is skipped; the worlds, the sampler stream and the
                # finalization below are unchanged
                means, batches, evaluations = np.zeros(1, dtype=np.float64), 0, 0
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
        if self.exact_lead_endgame:
            means, batches, winner, played, evaluations = self._exact_lead_decision(
                rnd, seat, admitted, worlds, started, check_budget,
                [float(preferences[i]) for i in chosen],
                (means, batches, winner, played, evaluations))
        confirmed = None
        if self.lead_confirm:
            # the held-out lead confirmation (class docstring): on a lead, once the
            # base decision and any exact lead stage are final
            self._lead_confirm = None
            if leading(rnd):
                confirmed = self._lead_confirm_decision(
                    rnd, seat, actions, preferences, chosen, worlds, started, check_budget,
                    winner, played, single_fast)
                if confirmed is not None:
                    chosen = list(chosen) + [confirmed]
                    admitted = admitted + [actions[confirmed]]
                    winner = len(chosen) - 1
                    played = list(actions[confirmed])
        exact_follow_record = None
        if self._exact_follow_eligible(rnd, admitted):
            # The normal PV result is complete before this optional stage starts.
            # Any refusal, budget expiry, or malformed world leaves it untouched.
            from .pv_exact_follow import rerank_follow
            baseline_winner, baseline_played = winner, list(played)
            soft_deadline = None
            if self.serving_budget_seconds is not None:
                soft_deadline = started + self.serving_budget_seconds * 0.8
            stage = OptionalStage(
                self, (), hard_check=check_budget,
                budget_errors=PVSearchBudgetExceeded, soft_deadline=soft_deadline,
                clock=time.perf_counter, soft_error=PVSearchBudgetExceeded,
                final_check=check_budget)
            exact = None
            solved = self._exact_worlds(worlds)
            with stage:
                if stage.guard is not None:
                    stage.guard()
                exact = rerank_follow(
                    rnd, seat, admitted, solved, baseline_index=winner,
                    max_nodes=self.exact_follow_max_nodes,
                    max_hand_cards=self.exact_follow_max_cards,
                    solver=self.exact_follow_solver,
                    check_budget=stage.guard)
                stage.raise_if_tripped()
                changed = exact.winner != baseline_winner
                if changed:
                    winner = exact.winner
                    played = list(admitted[winner])
                # Even an unchanged action publishes new exact scores/world
                # counts.  Only retain that evidence after a final budget check.
                stage.publish()
            if stage.abandoned:
                winner, played = baseline_winner, baseline_played
                exact_follow_record = {
                    "exact_follow_attempted": True,
                    "exact_follow_applied": False,
                    "exact_follow_abandoned": stage.reason,
                    "exact_follow_error": stage.error,
                }
            else:
                exact_follow_record = {
                    "exact_follow_attempted": True,
                    "exact_follow_applied": exact.winner != baseline_winner,
                    "exact_follow_abandoned": None,
                    "exact_follow_worlds": exact.worlds,
                    "exact_follow_nodes": exact.nodes,
                    "exact_follow_scores": list(exact.scores),
                }
            if solved is not worlds:
                exact_follow_record["exact_follow_subset_worlds"] = len(solved)
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
            **self._leaf_greedy_record(),
            **({"leaf_greedy_finish_exact_skipped": bool(self._leaf_greedy_exact_skipped)}
               if self.leaf_greedy_finish_exact_skip else {}),
            **self._leaf_greedy_deadline_record(),
            **self._leaf_greedy_top_record(),
            **self._lead_confirm_record(),
            **self._adaptive_worlds_record(),
            **self._soft_oracle_record(),
            **(self._exact_lead if self.exact_lead_endgame else {}),
            **({} if exact_follow_record is None else exact_follow_record),
        }
        if single_fast:
            # nothing priced the one candidate: its value is unknown, not zero
            self.last_decision_record.update(value_means=[None], single_candidate_fast=True)
        if confirmed is not None:
            # the confirmed challenger was priced on fresh worlds, not the base pass
            self.last_decision_record["value_means"] = means.tolist() + [None]
        return list(played)

    # -- the optional held-out lead confirmation (class docstring) ---------------

    def _lead_confirm_decision(self, rnd, seat, actions, preferences, chosen, worlds, started,
                               check_budget, winner, played, single_fast):
        """The legal index of a confirmed challenger to play instead of the
        final base lead, or None (the base decision stands); sets
        ``self._lead_confirm`` (the record fields)."""
        t0 = time.perf_counter()
        state = {"lead_confirm_status": None, "lead_confirm_pool": 0,
                 "lead_confirm_screen_worlds": 0, "lead_confirm_challengers": [],
                 "lead_confirm_screen_margins": [], "lead_confirm_worlds": 0,
                 "lead_confirm_deltas": [], "lead_confirm_ses": [],
                 "lead_confirm_applied": False, "lead_confirm_to": None,
                 "lead_confirm_seconds": 0.0}
        self._lead_confirm = state

        def finish(status, index=None):
            state.update(lead_confirm_status=status, lead_confirm_applied=index is not None,
                         lead_confirm_to=None if index is None else list(actions[index]),
                         lead_confirm_seconds=time.perf_counter() - t0)
            return index

        admitted = [actions[i] for i in chosen]
        if single_fast:
            return finish("single_candidate")
        if self.exact_lead_endgame and self._exact_lead_gate(rnd, admitted) is None:
            # an exact lead stage decided (or was entitled to decide) this lead
            return finish("exact")
        if sorted(played) != sorted(admitted[winner]):
            # a post-selection override (the doomed throw's forced component)
            return finish("override")
        budget = self.serving_budget_seconds
        if budget is not None and time.perf_counter() - started >= \
                self.lead_confirm_start_fraction * budget:
            return finish("skipped_budget")
        taken = set(chosen)
        ranked = sorted(range(len(actions)), key=lambda i: (-preferences[i], i))
        pool = [i for i in ranked if i not in taken and np.isfinite(preferences[i])]
        pool = pool[:max(0, self.lead_confirm - self._adaptive["k_used"])]
        state["lead_confirm_pool"] = len(pool)
        if not pool:
            return finish("no_pool")
        stage = OptionalStage(
            self, LEAD_CONFIRM_RULE_STATE, hard_check=check_budget,
            budget_errors=PVSearchBudgetExceeded,
            soft_deadline=(started + self.lead_confirm_soft_fraction * budget
                           if budget is not None else None),
            clock=time.perf_counter, soft_error=_AdaptiveWorldsExpired,
            final_check=check_budget, abandon_on=Exception,
            # the fresh draws overwrite the sampler record; it describes the base draw
            restore_always=("_last_sampling",))
        # the base pass's finished leaves and their record, kept by reference: the
        # stage's passes build their own and never mutate these
        kept = (self._leaf_greedy, self._leaf_greedy_pruned)
        served = admitted[winner]
        confirmed = None
        try:
            with stage:
                guard = stage.guard
                screen = list(worlds[:self.lead_confirm_screen_worlds])
                state["lead_confirm_screen_worlds"] = len(screen)
                matrix = self._lead_confirm_matrix(
                    rnd, seat, [served] + [actions[i] for i in pool], screen, guard)
                margins = matrix[:, 1:].mean(axis=0) - matrix[:, 0].mean()
                order = sorted(range(len(pool)), key=lambda j: (-margins[j], j))
                picks = [j for j in order if margins[j] > 0][:self.lead_confirm_challengers]
                if self.doomed_throw_reselect:
                    # a doomed throw is never played as led (the served rule's test)
                    picks = [j for j in picks
                             if self._doomed_component(rnd, seat, actions[pool[j]], worlds,
                                                       guard) is None]
                state.update(lead_confirm_challengers=[list(actions[pool[j]]) for j in picks],
                             lead_confirm_screen_margins=[float(margins[j]) for j in picks])
                if picks:
                    fresh = self._lead_confirm_draw(rnd, seat, guard)
                    state["lead_confirm_worlds"] = len(fresh)
                    matrix = self._lead_confirm_matrix(
                        rnd, seat, [served] + [actions[pool[j]] for j in picks], fresh, guard)
                    paired = matrix[:, 1:] - matrix[:, [0]]
                    deltas = paired.mean(axis=0)
                    ses = (paired.std(axis=0, ddof=1) / math.sqrt(len(fresh))
                           if len(fresh) >= 2 else np.full(len(picks), np.inf))
                    state.update(lead_confirm_deltas=[float(v) for v in deltas],
                                 lead_confirm_ses=[float(v) for v in ses])
                    passed = [t for t in range(len(picks))
                              if deltas[t] > self.lead_confirm_z * ses[t] + self.lead_confirm_margin]
                    if passed:
                        best = min(passed, key=lambda t: (-deltas[t], t))
                        confirmed = pool[picks[best]]
                stage.publish(changed=confirmed is not None)
        finally:
            self._leaf_greedy, self._leaf_greedy_pruned = kept
        if stage.abandoned:
            state.update(lead_confirm_abandon_reason=stage.reason,
                         lead_confirm_abandon_error=stage.error)
            return finish("abandoned")
        if confirmed is not None:
            return finish("applied", confirmed)
        return finish("rejected" if state["lead_confirm_challengers"] else "no_challenger")

    def _lead_confirm_matrix(self, rnd, seat, actions, worlds, check_budget):
        """``(worlds x actions)`` values on the served leaf: greedy-finished
        under ``leaf_greedy_finish`` (every leaf of this pass, the top-m
        restriction not applied), else `_leaf`.  A finish cut by its deadline
        raises: a pass that mixed leaves would not compare its candidates."""
        if self.leaf_greedy_finish and not self._leaf_greedy_exact_skipped:
            self._greedy_prefill(rnd, seat, actions, worlds, check_budget)
            if self._leaf_greedy["deadline_cut"]:
                raise _LeadConfirmLeafCut("the greedy finish passed its deadline")
        self._leaf_greedy_pruned = frozenset()
        matrix = np.full((len(worlds), len(actions)), np.nan, dtype=np.float64)
        self._score_leaves(rnd, seat, actions, worlds, check_budget, capture=matrix)
        if not np.isfinite(matrix).all():
            raise PVSearchPolicyError("lead_confirm value matrix has unfilled cells",
                                      stage="lead_confirm_matrix")
        return matrix

    def _lead_confirm_draw(self, rnd, seat, check_budget):
        """The fresh confirmation worlds: ``lead_confirm_rounds`` draws of W
        through this bot's own `_worlds` (the sampler stream advances)."""
        fresh = []
        for _ in range(self.lead_confirm_rounds):
            drawn, _attempts = self._worlds(rnd, seat, check_budget)
            fresh.extend(drawn)
        return fresh

    def _lead_confirm_record(self):
        if not self.lead_confirm or self._lead_confirm is None:
            return {}
        return dict(self._lead_confirm)

    def _single_candidate_fast(self, rnd, admitted):
        """``single_candidate_fast`` applies: on, one admitted candidate, the
        served value pass (no subclass override, no greedy leaf whose record the
        pass fills) and no exact lead stage that would start on it."""
        return bool(self.single_candidate_fast and len(admitted) == 1
                    and not self.leaf_greedy_finish
                    and type(self)._value_means is PVSearchBot._value_means
                    and type(self)._score_leaves is PVSearchBot._score_leaves
                    and not (self.exact_lead_endgame
                             and self._exact_lead_gate(rnd, admitted) is None))

    def _exact_worlds(self, worlds):
        """The worlds an exact stage solves: ``worlds`` itself, or with
        ``exact_world_subset`` narrower than them its first ``exact_world_subset``
        in draw order, equally weighted (module docstring)."""
        n = self.exact_world_subset
        if not n or len(worlds) <= n:
            return worlds
        return list(worlds[:n])

    def _exact_follow_eligible(self, rnd, admitted):
        """The exact follow stage's gate: on, a follow with more than one
        admitted candidate and every hand within its card bound."""
        return bool(self.exact_follow and len(admitted) > 1
                    and rnd.trick is not None and rnd.trick.plays
                    and max(map(len, rnd.hands)) <= self.exact_follow_max_cards)

    def _exact_lead_gate(self, rnd, admitted):
        """The exact lead stage's gate before its budget check: None when the
        stage would start, else the status it records (``'ineligible'``: not a
        lead or a hand above the card bound; ``'single_candidate'``: the deeper
        rule with one admitted candidate, which an exact pass cannot change)."""
        deep = self.exact_deep_cards
        max_cards = deep or EXACT_LEAD_LIMITS['max_hand_cards']
        if not leading(rnd) or max(map(len, rnd.hands)) > max_cards:
            return 'ineligible'
        if deep and len(admitted) == 1:
            return 'single_candidate'
        return None

    def _exact_lead_decision(self, rnd, seat, admitted, worlds, started, check_budget, priors, base):
        """Complete baseline first; replace only with a complete bounded exact pass.

        Exact continuation is within sampled worlds, never the live hidden deal.
        OptionalStage also restores selection-rule records on an absorbed expiry.
        """
        from .pv_exact_endgame import exact_lead_means
        state = dict(exact_lead_status='ineligible', exact_lead_worlds_completed=0,
                     exact_lead_nodes=None, exact_lead_cache_hits=None,
                     exact_lead_changed=False)
        self._exact_lead = state
        deep = self.exact_deep_cards
        max_cards = deep or EXACT_LEAD_LIMITS['max_hand_cards']
        if deep:
            state['exact_deep_cards'] = deep
        gate = self._exact_lead_gate(rnd, admitted)
        if gate is not None:
            state['exact_lead_status'] = gate
            return base
        now = time.perf_counter()
        budget = self.serving_budget_seconds
        if budget is not None and now - started >= EXACT_LEAD_LIMITS['start_fraction'] * budget:
            state['exact_lead_status'] = 'skipped_budget'
            return base
        deadline = now + self.exact_lead_max_seconds
        if budget is not None:
            deadline = min(deadline, started + EXACT_LEAD_LIMITS['soft_fraction'] * budget)
        stage = OptionalStage(self, ADAPTIVE_WORLDS_RULE_STATE, hard_check=check_budget,
            budget_errors=PVSearchBudgetExceeded, soft_deadline=deadline,
            clock=lambda: time.perf_counter(), soft_error=_AdaptiveWorldsExpired,
            final_check=check_budget, abandon_on=Exception)
        policy_first = None
        if self.exact_lead_policy_first:
            # the ``elp`` variant (module docstring): same stage, guard and fallback
            from .exact_lead_policy_first import ExactLeadPolicyFirst
            policy_first = ExactLeadPolicyFirst(
                self.predict, self.version, check_budget=stage.guard,
                seed=f'elp|{self.seed}|{len(rnd.history)}|{seat}',
                view_worlds=EXACT_LEAD_POLICY_LIMITS['view_worlds'])
        kept_index = None
        # the solved worlds: every world, or the pinned subset (a prefix, so a
        # world keeps its index); the selection rules below read every world
        solved = self._exact_worlds(worlds)
        if solved is not worlds:
            state['exact_lead_subset_worlds'] = len(solved)
        with stage:
            leaf_fn = (self._leaf if policy_first is None
                       else policy_first.leaf_fn(rnd, seat, admitted, solved))
            if deep:
                # the deeper rule (module docstring)
                from .pv_exact_deep import exact_root_means
                means, stats = exact_root_means(
                    rnd, seat, admitted, solved, leaf_fn, stage.guard, max_hand_cards=max_cards,
                    max_nodes=self.exact_deep_max_nodes)
            else:
                means, stats = exact_lead_means(rnd, seat, admitted, solved, leaf_fn, stage.guard,
                                               max_nodes=EXACT_LEAD_LIMITS['max_nodes'])
            stage.guard()
            # ``exact=True``: the doomed-throw re-select's exact-stage guard
            # (`policy_value_search`) floors its replacements at this selection's mean
            winner = self._select(rnd, seat, admitted, means, worlds=worlds,
                                  check_budget=stage.guard, priors=priors, exact=True)
            played = self._swap_doomed_throw(rnd, seat, admitted[winner], worlds, stage.guard)
            stage.guard()
            if self.exact_lead_tie_baseline and not means[winner] > means[base[2]]:
                # the ``elt`` variant: no strict exact improvement keeps the
                # finalized baseline lead and its selection-rule records
                stage.restore()
                kept_index, winner, played = int(winner), base[2], list(base[3])
            stage.publish()
        state['exact_lead_seconds'] = time.perf_counter() - now
        if policy_first is not None:
            state.update(exact_lead_first_trick='policy', **policy_first.counters())
        if self.exact_lead_tie_baseline:
            state.update(exact_lead_tie_baseline_kept=kept_index is not None,
                         exact_lead_tie_baseline_exact_index=kept_index)
        if stage.abandoned:
            state.update(exact_lead_status='abandoned', exact_lead_worlds_completed=None,
                         exact_lead_abandon_reason=stage.reason, exact_lead_abandon_error=stage.error)
            return base
        # Scalar witnesses survive trace_fields even when a widened ballot's
        # means exceed its numeric-list limit. These compare TWO exact means,
        # never an exact level with the baseline value head's prediction.
        selected_level = float(means[winner])
        base_level = float(means[base[2]])
        delta = selected_level - base_level
        changed = sorted(played) != sorted(base[3])
        aligned = (sorted(played) == sorted(admitted[winner])
                   and sorted(base[3]) == sorted(admitted[base[2]]))
        change_kind = ('unchanged' if not changed else 'post_selection_override' if not aligned
                       else 'higher' if delta > 0 else 'lower' if delta < 0 else 'tie')
        state.update(exact_lead_status='complete', exact_lead_worlds_completed=stats['worlds_completed'],
                     exact_lead_nodes=stats['nodes'], exact_lead_cache_hits=stats['cache_hits'],
                     exact_lead_changed=changed,
                     exact_lead_change_kind=change_kind,
                     exact_lead_selected_level_mean=selected_level,
                     exact_lead_base_level_mean=base_level,
                     exact_lead_selected_level_delta=delta,
                     exact_lead_base_selected_index=int(base[2]),
                     exact_lead_base_value_means=base[0].tolist(),
                     exact_lead_base_played=list(base[3]))
        return means, base[1], winner, played, base[4]

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
        """The sampler rules' fields for the decision record: the refusal
        rule's while it is on (zeros when no refusal constrained this
        decision), the history test's while it is on; neither when both are off."""
        out = {}
        if self.refusal_constraints:
            out.update(refusal_observations=0, refusal_rejections=0,
                       refusal_fallback_worlds=0, refusal_pinned_codes=0)
        if getattr(self, "world_history_legal", False):
            out.update(history_follow_events=0, history_rejections=0,
                       history_fallback_worlds=0, history_rejections_by_age={})
            if getattr(self, "world_history_draw", False):
                out.update(history_draw_constraints=0, history_draw_forbidden=0)
        if getattr(self, "belief_worlds", False):
            out.update(belief_fallback=0, belief_proposed=0, belief_ms=0.0)
            if self.belief_log:
                out["belief_log"] = 1
        if not out:
            return {}
        return {**out, **self._last_sampling}

    def _sampler_counts(self):
        return {name: int(getattr(self.sampler, name, 0)) for name in SAMPLER_DELTA_COUNTERS}

    def decide_play(self, rnd, seat):
        started = time.perf_counter()
        counts = self._sampler_counts()
        try:
            return self._decide_play(rnd, seat, started)
        finally:
            if self.leaf_cache_release and self._leaf_greedy is not None:
                # the finished leaves serve one decision only (`_search` resets
                # them); dropped here, the server's per-turn copy of this bot
                # does not copy them
                self._leaf_greedy['cache'] = {}
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
        # the diagnostic oracle refuses BEFORE the fallback below can absorb
        # anything: an unbound hook is a configuration error, not a search error
        self._require_oracle_bound()
        anchor = HeuristicBot.decide_play(self, rnd, seat)
        if self.serving_budget_seconds is None:
            return self._search(rnd, seat, anchor, started)
        before = self.sampler.rng.getstate()

        def check_budget():
            if time.perf_counter() - started >= self.serving_budget_seconds:
                raise PVSearchBudgetExceeded("pv-search serving budget expired")

        try:
            return self._search(rnd, seat, anchor, started, check_budget)
        except OracleWorldsError:
            # the diagnostic never degrades to the heuristic (module docstring)
            raise
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

    #: the optional wide value-only chooser (`bury_wide_value`; module docstring),
    #: OFF: class defaults, so a flag-off bot's instance state is exactly what it was
    bury_wide_value = BURY_WIDE_VALUE_DEFAULTS["bury_wide_value"]
    bury_wide_k = BURY_WIDE_VALUE_DEFAULTS["bury_wide_k"]
    bury_wide_swaps = BURY_WIDE_SWAPS_DEFAULT
    #: its optional second stage (`bury_two_stage`): None (off) or a config
    bury_two_stage = None
    #: its optional kitty charge (`bury_kitty_charge`): OFF
    bury_kitty_charge = False

    def __init__(self, predict, *, evaluator, version: int, config: PVSearchConfig,
                 checkpoint: str, seed: int = 0, bury_arm: str = "hybrid",
                 bury_config: CWVBuryConfig | None = None, bury_serving_budget_seconds=None,
                 bury_wide_value: bool = BURY_WIDE_VALUE_DEFAULTS["bury_wide_value"],
                 bury_wide_k: int = BURY_WIDE_VALUE_DEFAULTS["bury_wide_k"],
                 bury_wide_swaps: int = BURY_WIDE_SWAPS_DEFAULT,
                 bury_two_stage: BuryTwoStageConfig | None = None,
                 bury_kitty_charge: bool = False):
        if bury_arm not in BURY_ARMS:
            raise BuryPolicyError(f"unknown bury arm {bury_arm!r}")
        _check_bury_wide_value(bury_arm, bury_wide_value, bury_wide_k, bury_wide_swaps)
        _check_bury_two_stage(bury_wide_value, bury_two_stage)
        _check_bury_kitty_charge(config, bury_wide_value, bury_two_stage, bury_kitty_charge)
        # bound before the base constructor: its ``leaf_policy_first_trick`` effect
        # check asks whether a model bury arm (a value leaf) exists
        self._leaf_bury_arm = bury_arm
        super().__init__(predict, evaluator=evaluator, version=version, config=config,
                         checkpoint=checkpoint, seed=seed)
        self.bury_arm = bury_arm
        self.bury_config = CWVBuryConfig() if bury_config is None else bury_config
        if not isinstance(self.bury_config, CWVBuryConfig):
            raise TypeError("bury_config must be a CWVBuryConfig")
        self.bury_serving_budget_seconds = _bury_budget(bury_serving_budget_seconds)
        self.last_bury_record = None
        if bury_wide_value:
            # instance state only when on (as the declare rules): a flag-off bot's
            # attributes are exactly what they were
            self.bury_wide_value = True
            self.bury_wide_k = bury_wide_k
            if bury_wide_swaps != BURY_WIDE_SWAPS_DEFAULT:
                # likewise: a swaps=1 bot is exactly today's flag-on bot
                self.bury_wide_swaps = bury_wide_swaps
            if bury_two_stage is not None:
                # likewise: a bot without the second stage is exactly release 45's
                self.bury_two_stage = bury_two_stage
            if bury_kitty_charge:
                # likewise: a bot without the charge is exactly release 46's
                self.bury_kitty_charge = True
        if self.value_declare_served_bury and not self.bury_wide_value:
            raise PVSearchPolicyError(_VALUE_DECLARE_SERVED_BURY_NO_EFFECT)

    def _bury_rng(self):
        return self.sampler.rng

    def _decide_bury(self, rnd, seat, *, started=None, incumbent=None, check_budget=None,
                     progress=None):
        """The mixin's search, or (``bury_wide_value``) the wide value-only
        chooser (`bury_wide_value.decide_wide_value_bury`) in its slot: the
        mixin's `decide_bury` keeps the budget clock, the incumbent and the
        fallback either way."""
        if not self.bury_wide_value:
            return super()._decide_bury(rnd, seat, started=started, incumbent=incumbent,
                                        check_budget=check_budget, progress=progress)
        started = time.perf_counter() if started is None else started
        if getattr(rnd, "phase", None) != "bury" or getattr(rnd, "banker", None) != seat:
            raise BuryPolicyError("bury policy requires the banker in bury phase")
        if incumbent is None:
            incumbent = list(super(CWVBuryMixin, self).decide_bury(rnd, seat))
        if progress is None:
            progress = {"mc_rollouts": 0, "model_positions": 0}
        return decide_wide_value_bury(self, rnd, seat, started=started, incumbent=incumbent,
                                      check_budget=check_budget, progress=progress)

    def _leaf_first_trick(self, fallback, check_budget=None):
        """The bury leaf's first-trick player (`CWVBuryMixin._leaf_first_trick`):
        the policy head under ``leaf_policy_first_trick``, else None (the
        heuristic continuation, ``fallback``)."""
        return self._policy_first_trick(fallback, check_budget)


def _check_wide_k(k) -> int:
    try:
        k = check_wide_k(k)
    except BuryPolicyError as exc:
        raise PVSearchPolicyError(str(exc)) from None
    if k > BURY_WIDE_K_MAX:
        raise PVSearchPolicyError(f"bury_wide_k must be an int >= 2 and <= {BURY_WIDE_K_MAX}")
    return k


def _check_wide_swaps(swaps) -> int:
    try:
        return check_wide_swaps(swaps)
    except BuryPolicyError as exc:
        raise PVSearchPolicyError(str(exc)) from None


def _check_bury_wide_value(bury_arm, bury_wide_value, bury_wide_k,
                           bury_wide_swaps=BURY_WIDE_SWAPS_DEFAULT) -> None:
    """``bury_wide_value`` is a bool and needs a model bury arm (the chooser
    replaces the arm's value pass and MC stage; on ``heuristic`` or ``mc`` a
    token for a chooser with no effect would be a lie); ``bury_wide_k`` (an
    int in [2, ``BURY_WIDE_K_MAX``]) and ``bury_wide_swaps`` (1 or 2) are
    checked only with the flag on and must be the defaults off."""
    if type(bury_wide_value) is not bool:
        raise PVSearchPolicyError("bury_wide_value must be a bool")
    if bury_wide_value:
        if bury_arm not in BURY_MODEL_ARMS:
            raise PVSearchPolicyError(_BURY_WIDE_VALUE_NO_EFFECT)
        _check_wide_k(bury_wide_k)
        _check_wide_swaps(bury_wide_swaps)
    else:
        if bury_wide_k != BURY_WIDE_VALUE_DEFAULTS["bury_wide_k"]:
            raise PVSearchPolicyError(_BURY_WIDE_K_REQUIRES)
        if type(bury_wide_swaps) is not int or bury_wide_swaps != BURY_WIDE_SWAPS_DEFAULT:
            raise PVSearchPolicyError(_BURY_WIDE_SWAPS_REQUIRES)


def _check_bury_two_stage(bury_wide_value, bury_two_stage) -> None:
    """``bury_two_stage`` is None (off) or a `bury_two_stage.TwoStageConfig`,
    and it needs the wide chooser it extends."""
    if bury_two_stage is None:
        return
    if type(bury_two_stage) is not BuryTwoStageConfig:
        raise PVSearchPolicyError("bury_two_stage must be a TwoStageConfig or None")
    if not bury_wide_value:
        raise PVSearchPolicyError(_BURY_TWO_STAGE_REQUIRES)


def _check_bury_kitty_charge(config: PVSearchConfig, bury_wide_value, bury_two_stage,
                             bury_kitty_charge) -> None:
    """``bury_kitty_charge`` is a bool and needs the wide chooser it charges;
    the second stage and the declaration's served-bury model choose without
    it, so it refuses them."""
    if type(bury_kitty_charge) is not bool:
        raise PVSearchPolicyError("bury_kitty_charge must be a bool")
    if not bury_kitty_charge:
        return
    if not bury_wide_value:
        raise PVSearchPolicyError(_BURY_KITTY_CHARGE_REQUIRES)
    if bury_two_stage is not None or config.value_declare_served_bury:
        raise PVSearchPolicyError(_BURY_KITTY_CHARGE_EXCLUSIVE)


def _check_leaf_policy_effect(config: PVSearchConfig, bury_arm) -> None:
    """``leaf_policy_first_trick`` needs a value leaf it changes (module
    docstring): the value declaration, or a model bury arm."""
    if config.leaf_policy_first_trick and not config.value_declare \
            and bury_arm not in BURY_MODEL_ARMS:
        raise PVSearchPolicyError(_LEAF_POLICY_NO_EFFECT)


def _check_served_bury_effect(config: PVSearchConfig, bury_arm, bury_wide_value) -> None:
    """``value_declare_served_bury`` needs the served wide value-only chooser
    (module docstring): a model bury arm with ``bury_wide_value`` on."""
    if config.value_declare_served_bury and (bury_arm not in BURY_MODEL_ARMS
                                             or not bury_wide_value):
        raise PVSearchPolicyError(_VALUE_DECLARE_SERVED_BURY_NO_EFFECT)


def _check_oracle_hook(oracle_worlds, oracle_deal, oracle_mix_k=0, oracle_pin_q=0.0) -> None:
    """The diagnostic oracle and its soft variants are NEVER served (module
    docstring): with any of them on, construction needs the screen harness's
    true-deal hook; with all off, a hook is refused (a served bot must not
    carry one).  Checked before any package is read, so a served process
    refuses without touching the model."""
    if type(oracle_worlds) is not bool:
        raise PVSearchPolicyError("oracle_worlds must be a bool")
    soft = bool(oracle_mix_k) or bool(oracle_pin_q)
    if oracle_worlds and oracle_deal is None:
        raise PVSearchPolicyError(_ORACLE_NOT_SERVED)
    if soft and oracle_deal is None:
        raise PVSearchPolicyError(_SOFT_ORACLE_NOT_SERVED)
    if oracle_deal is not None and not (oracle_worlds or soft):
        raise PVSearchPolicyError(_ORACLE_HOOK_WITHOUT_RULE)


def _require_pv_search(bot, name: str):
    """REFUSE anything that is not the production wrapper under a pv-search name."""
    if not isinstance(bot, PVSearchBot):
        raise PVSearchPolicyError(f"policy {name!r} built {type(bot).__name__}, not PVSearchBot")
    return bot


_BELIEF_MODELS: dict = {}


def _check_belief_binding(config: PVSearchConfig, belief_checkpoint) -> None:
    if config.belief_worlds and not belief_checkpoint:
        raise PVSearchPolicyError("belief_worlds needs the belief package (SHENGJI_PV_BELIEF_CKPT)")
    if belief_checkpoint and not config.belief_worlds:
        raise PVSearchPolicyError("a belief package needs belief_worlds (SHENGJI_PV_BELIEF_WORLDS=1)")


def _load_belief(path, sha256: str):
    """The belief package, sha-verified, loaded once per process and shared
    (read-only) by every bot that binds it."""
    from ..ai.belief_numpy import load_belief_numpy
    key = (str(path), sha256)
    if key not in _BELIEF_MODELS:
        _BELIEF_MODELS[key] = load_belief_numpy(path, sha256)
    return _BELIEF_MODELS[key]


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
                       world_history_legal: bool = SAMPLER_DEFAULTS["world_history_legal"],
                       world_history_draw: bool = SAMPLER_DEFAULTS["world_history_draw"],
                       belief_worlds: bool = SAMPLER_DEFAULTS["belief_worlds"],
                       belief_capacity: bool = SAMPLER_DEFAULTS["belief_capacity"],
                       belief_checkpoint: str | None = None,
                       belief_sha256: str | None = None,
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
                       finish_lead_admission: bool = False,
                       exact_lead_endgame: bool = False,
                       exact_lead_tie_baseline: bool = False,
                       exact_lead_policy_first: bool = False,
                       exact_deep_cards: int = 0,
                       exact_lead_max_seconds: float = EXACT_LEAD_CAP_DEFAULTS["exact_lead_max_seconds"],
                       exact_deep_max_nodes: int = EXACT_LEAD_CAP_DEFAULTS["exact_deep_max_nodes"],
                       exact_follow: bool = False,
                       exact_follow_max_nodes: int = 250_000,
                       exact_follow_solver: str = "reference",
                       exact_follow_max_cards: int = 4,
                       exact_world_subset: int = 0,
                       doomed_throw_reselect: bool = DOOMED_THROW_RESELECT_DEFAULTS["doomed_throw_reselect"],
                       doomed_throw_reselect_exact_guard: bool = DOOMED_THROW_RESELECT_EXACT_GUARD_DEFAULTS["doomed_throw_reselect_exact_guard"],
                       leaf_greedy_finish: bool = LEAF_GREEDY_DEFAULTS["leaf_greedy_finish"],
                       leaf_greedy_finish_exact_skip: bool = LEAF_GREEDY_EXACT_SKIP_DEFAULTS["leaf_greedy_finish_exact_skip"],
                       leaf_greedy_deadline_ms: int = 0,
                       leaf_greedy_top: int = 0,
                       wide_lead_k: int = WIDE_LEAD_K,
                       lead_confirm: int = 0,
                       value_declare: bool = VALUE_DECLARE_DEFAULTS["value_declare"],
                       value_declare_worlds: int = VALUE_DECLARE_DEFAULTS["value_declare_worlds"],
                       value_declare_margin: float = VALUE_DECLARE_DEFAULTS["value_declare_margin"],
                       value_declare_every_first: bool = VALUE_DECLARE_EVERY_FIRST_DEFAULTS["value_declare_every_first"],
                       value_declare_served_bury: bool = VALUE_DECLARE_SERVED_BURY_DEFAULTS["value_declare_served_bury"],
                       value_declare_pass_worlds: bool = VALUE_DECLARE_PASS_WORLDS_DEFAULTS["value_declare_pass_worlds"],
                       value_declare_wait: bool = VALUE_DECLARE_WAIT_DEFAULTS["value_declare_wait"],
                       declare_asap_first: bool = DECLARE_ASAP_DEFAULTS["declare_asap_first"],
                       leaf_policy_first_trick: bool = LEAF_POLICY_DEFAULTS["leaf_policy_first_trick"],
                       bury_wide_value: bool = BURY_WIDE_VALUE_DEFAULTS["bury_wide_value"],
                       bury_wide_k: int = BURY_WIDE_VALUE_DEFAULTS["bury_wide_k"],
                       bury_wide_swaps: int = BURY_WIDE_SWAPS_DEFAULT,
                       bury_two_stage: BuryTwoStageConfig | None = None,
                       bury_kitty_charge: bool = False,
                       oracle_worlds: bool = ORACLE_WORLDS_DEFAULTS["oracle_worlds"],
                       oracle_deal=None,
                       oracle_mix_k: int = ORACLE_SOFT_DEFAULTS["oracle_mix_k"],
                       oracle_pin_q: float = ORACLE_SOFT_DEFAULTS["oracle_pin_q"]
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
    # the diagnostics are never served: first
    _check_oracle_hook(oracle_worlds, oracle_deal, oracle_mix_k, oracle_pin_q)
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
                            world_history_legal=world_history_legal,
                            world_history_draw=world_history_draw,
                            belief_worlds=belief_worlds, belief_sha256=belief_sha256,
                            belief_capacity=belief_capacity,
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
                            finish_lead_admission=finish_lead_admission,
                            exact_lead_endgame=exact_lead_endgame,
                            exact_lead_tie_baseline=exact_lead_tie_baseline,
                            exact_lead_policy_first=exact_lead_policy_first,
                            exact_deep_cards=exact_deep_cards,
                            exact_lead_max_seconds=exact_lead_max_seconds,
                            exact_deep_max_nodes=exact_deep_max_nodes,
                            exact_follow=exact_follow,
                            exact_follow_max_nodes=exact_follow_max_nodes,
                            exact_follow_solver=exact_follow_solver,
                            exact_follow_max_cards=exact_follow_max_cards,
                            exact_world_subset=exact_world_subset,
                            doomed_throw_reselect=doomed_throw_reselect,
                            doomed_throw_reselect_exact_guard=doomed_throw_reselect_exact_guard,
                            leaf_greedy_finish=leaf_greedy_finish,
                            leaf_greedy_finish_exact_skip=leaf_greedy_finish_exact_skip,
                            leaf_greedy_deadline_ms=leaf_greedy_deadline_ms,
                            leaf_greedy_top=leaf_greedy_top, wide_lead_k=wide_lead_k,
                            lead_confirm=lead_confirm,
                            value_declare=value_declare,
                            value_declare_worlds=value_declare_worlds,
                            value_declare_margin=value_declare_margin,
                            value_declare_every_first=value_declare_every_first,
                            value_declare_served_bury=value_declare_served_bury,
                            value_declare_pass_worlds=value_declare_pass_worlds,
                            value_declare_wait=value_declare_wait,
                            declare_asap_first=declare_asap_first,
                            leaf_policy_first_trick=leaf_policy_first_trick,
                            oracle_worlds=oracle_worlds,
                            oracle_mix_k=oracle_mix_k, oracle_pin_q=oracle_pin_q)
    recipe_payload(config)   # refuses a non-bool rule flag before anything loads
    _check_belief_binding(config, belief_checkpoint)
    _check_leaf_policy_effect(config, bury_arm)
    _check_bury_wide_value(bury_arm, bury_wide_value, bury_wide_k, bury_wide_swaps)
    _check_bury_two_stage(bury_wide_value, bury_two_stage)
    _check_bury_kitty_charge(config, bury_wide_value, bury_two_stage, bury_kitty_charge)
    _check_served_bury_effect(config, bury_arm, bury_wide_value)
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
        # the wide chooser's keywords only when on: a flag-off construction is
        # the call it always was (a diagnostic ``bot_factory`` need not know them)
        wide = ({"bury_wide_value": True, "bury_wide_k": bury_wide_k}
                if bury_wide_value else {})
        if bury_wide_value and bury_wide_swaps != BURY_WIDE_SWAPS_DEFAULT:
            wide["bury_wide_swaps"] = bury_wide_swaps
        if bury_two_stage is not None:
            wide["bury_two_stage"] = bury_two_stage
        if bury_kitty_charge:
            wide["bury_kitty_charge"] = True
        bot = build(predict, evaluator=evaluator, version=predict.version, config=config,
                    checkpoint=path, seed=int(seed), bury_arm=bury_arm,
                    bury_config=bury_config,
                    bury_serving_budget_seconds=bury_serving_budget_seconds, **wide)
    if not isinstance(bot, expected):
        raise PVSearchPolicyError(
            f"bot_factory built {type(bot).__name__}, not a {expected.__name__}")
    bot.prior_checkpoint = None if prior_checkpoint is None else str(prior_checkpoint)
    bot.prior_sha256 = prior_sha256
    if config.belief_worlds:
        bot.belief_model = _load_belief(belief_checkpoint, belief_sha256)
        bot.belief_checkpoint = str(belief_checkpoint)
        # the log flag is read where the package is bound, from the serving
        # environment: an instance attribute only when it differs from the default
        if belief_log_enabled() != BELIEF_LOG_DEFAULT:
            bot.belief_log = not BELIEF_LOG_DEFAULT
    # the latency switches, read from the serving environment where the bot is
    # built: instance attributes only when on
    for attr, on in latency_switches().items():
        if on:
            setattr(bot, attr, True)
    if oracle_deal is not None:
        bot.bind_oracle_deal(oracle_deal)
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
                        world_history_legal: bool = SAMPLER_DEFAULTS["world_history_legal"],
                        world_history_draw: bool = SAMPLER_DEFAULTS["world_history_draw"],
                        belief_worlds: bool = SAMPLER_DEFAULTS["belief_worlds"],
                        belief_capacity: bool = SAMPLER_DEFAULTS["belief_capacity"],
                        belief_checkpoint: str | None = None,
                        belief_sha256: str | None = None,
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
                        finish_lead_admission: bool = False,
                        exact_lead_endgame: bool = False,
                        exact_lead_tie_baseline: bool = False,
                        exact_lead_policy_first: bool = False,
                        exact_deep_cards: int = 0,
                        exact_lead_max_seconds: float = EXACT_LEAD_CAP_DEFAULTS["exact_lead_max_seconds"],
                        exact_deep_max_nodes: int = EXACT_LEAD_CAP_DEFAULTS["exact_deep_max_nodes"],
                        exact_follow: bool = False,
                        exact_follow_max_nodes: int = 250_000,
                        exact_follow_solver: str = "reference",
                        exact_follow_max_cards: int = 4,
                        exact_world_subset: int = 0,
                        doomed_throw_reselect: bool = DOOMED_THROW_RESELECT_DEFAULTS["doomed_throw_reselect"],
                        doomed_throw_reselect_exact_guard: bool = DOOMED_THROW_RESELECT_EXACT_GUARD_DEFAULTS["doomed_throw_reselect_exact_guard"],
                        leaf_greedy_finish: bool = LEAF_GREEDY_DEFAULTS["leaf_greedy_finish"],
                        leaf_greedy_finish_exact_skip: bool = LEAF_GREEDY_EXACT_SKIP_DEFAULTS["leaf_greedy_finish_exact_skip"],
                        leaf_greedy_deadline_ms: int = 0,
                        leaf_greedy_top: int = 0,
                        wide_lead_k: int = WIDE_LEAD_K,
                        lead_confirm: int = 0,
                        value_declare: bool = VALUE_DECLARE_DEFAULTS["value_declare"],
                        value_declare_worlds: int = VALUE_DECLARE_DEFAULTS["value_declare_worlds"],
                        value_declare_margin: float = VALUE_DECLARE_DEFAULTS["value_declare_margin"],
                        value_declare_every_first: bool = VALUE_DECLARE_EVERY_FIRST_DEFAULTS["value_declare_every_first"],
                        value_declare_served_bury: bool = VALUE_DECLARE_SERVED_BURY_DEFAULTS["value_declare_served_bury"],
                        value_declare_pass_worlds: bool = VALUE_DECLARE_PASS_WORLDS_DEFAULTS["value_declare_pass_worlds"],
                        value_declare_wait: bool = VALUE_DECLARE_WAIT_DEFAULTS["value_declare_wait"],
                        declare_asap_first: bool = DECLARE_ASAP_DEFAULTS["declare_asap_first"],
                        leaf_policy_first_trick: bool = LEAF_POLICY_DEFAULTS["leaf_policy_first_trick"],
                        bury_wide_value: bool = BURY_WIDE_VALUE_DEFAULTS["bury_wide_value"],
                        bury_wide_k: int = BURY_WIDE_VALUE_DEFAULTS["bury_wide_k"],
                        bury_wide_swaps: int = BURY_WIDE_SWAPS_DEFAULT,
                        bury_two_stage: BuryTwoStageConfig | None = None,
                        bury_kitty_charge: bool = False,
                        oracle_worlds: bool = ORACLE_WORLDS_DEFAULTS["oracle_worlds"],
                        oracle_mix_k: int = ORACLE_SOFT_DEFAULTS["oracle_mix_k"],
                        oracle_pin_q: float = ORACLE_SOFT_DEFAULTS["oracle_pin_q"]
                        ) -> dict:
    """``{name: factory}`` for one recipe; the factory takes ``seed=`` from `make_bot`.
    With ``bury_arm`` the name carries the bury identity exactly as the shortlist's
    bury wrapper does: ``<play name>-bury-<arm>-<12 hex of the cwv-bury-recipe-v1 identity>``;
    with ``bury_wide_value`` the identity gains ``wide_value`` (the chooser and its
    ``k``) and the name the token: ``<play name>-bury-<arm>-bwv-<12 hex>``."""
    from ..ai.cwv_policy import checkpoint_id
    config = PVSearchConfig(checkpoint_sha256=sha256, tree=tree, worlds=int(worlds), candidates=int(candidates),
                            cap=int(cap), batch_size=int(batch_size),
                            serving_budget_seconds=_serving_budget(serving_budget_seconds),
                            refusal_constraints=refusal_constraints,
                            refusal_event_complete=refusal_event_complete,
                            world_history_legal=world_history_legal,
                            world_history_draw=world_history_draw,
                            belief_worlds=belief_worlds, belief_sha256=belief_sha256,
                            belief_capacity=belief_capacity,
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
                            finish_lead_admission=finish_lead_admission,
                            exact_lead_endgame=exact_lead_endgame,
                            exact_lead_tie_baseline=exact_lead_tie_baseline,
                            exact_lead_policy_first=exact_lead_policy_first,
                            exact_deep_cards=exact_deep_cards,
                            exact_lead_max_seconds=exact_lead_max_seconds,
                            exact_deep_max_nodes=exact_deep_max_nodes,
                            exact_follow=exact_follow,
                            exact_follow_max_nodes=exact_follow_max_nodes,
                            exact_follow_solver=exact_follow_solver,
                            exact_follow_max_cards=exact_follow_max_cards,
                            exact_world_subset=exact_world_subset,
                            doomed_throw_reselect=doomed_throw_reselect,
                            doomed_throw_reselect_exact_guard=doomed_throw_reselect_exact_guard,
                            leaf_greedy_finish=leaf_greedy_finish,
                            leaf_greedy_finish_exact_skip=leaf_greedy_finish_exact_skip,
                            leaf_greedy_deadline_ms=leaf_greedy_deadline_ms,
                            leaf_greedy_top=leaf_greedy_top, wide_lead_k=wide_lead_k,
                            lead_confirm=lead_confirm,
                            value_declare=value_declare,
                            value_declare_worlds=value_declare_worlds,
                            value_declare_margin=value_declare_margin,
                            value_declare_every_first=value_declare_every_first,
                            value_declare_served_bury=value_declare_served_bury,
                            value_declare_pass_worlds=value_declare_pass_worlds,
                            value_declare_wait=value_declare_wait,
                            declare_asap_first=declare_asap_first,
                            leaf_policy_first_trick=leaf_policy_first_trick,
                            oracle_worlds=oracle_worlds,
                            oracle_mix_k=oracle_mix_k, oracle_pin_q=oracle_pin_q)
    recipe_payload(config)   # refuses a non-bool rule flag
    _check_belief_binding(config, belief_checkpoint)
    if config.belief_worlds and file_sha256(str(belief_checkpoint)) != config.belief_sha256:
        raise PVSearchPolicyError("belief package on disk does not match SHENGJI_PV_BELIEF_SHA256")
    _check_leaf_policy_effect(config, bury_arm)
    _check_bury_wide_value(bury_arm, bury_wide_value, bury_wide_k, bury_wide_swaps)
    _check_bury_two_stage(bury_wide_value, bury_two_stage)
    _check_bury_kitty_charge(config, bury_wide_value, bury_two_stage, bury_kitty_charge)
    _check_served_bury_effect(config, bury_arm, bury_wide_value)
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
        token = ""
        if bury_wide_value:
            bury_identity["wide_value"] = {"chooser": BURY_WIDE_CHOOSER, "k": int(bury_wide_k)}
            token = f"-{BURY_WIDE_TOKEN}"
            if bury_wide_swaps != BURY_WIDE_SWAPS_DEFAULT:
                # two-card swaps: only then does the identity (and the token) change
                bury_identity["wide_value"]["swaps"] = int(bury_wide_swaps)
                token = f"-{BURY_WIDE_TOKEN_TWO_SWAPS}"
            if bury_two_stage is not None:
                # the second stage: only then does the identity gain it (and the name its token)
                bury_identity["wide_value"]["two_stage"] = bury_two_stage.identity()
                token += f"-{BURY_TWO_STAGE_TOKEN}"
            if bury_kitty_charge:
                # the kitty charge: only then does the identity gain it (and the name its token)
                bury_identity["wide_value"]["kitty_charge"] = bury_kitty_charge_identity()
                token += f"-{BURY_KITTY_CHARGE_TOKEN}"
        encoded = json.dumps(bury_identity, sort_keys=True, separators=(",", ":")).encode()
        name = f"{name}-bury-{bury_arm}{token}-{hashlib.sha256(encoded).hexdigest()[:12]}"
        bury_config, bury_serving_budget_seconds = bconfig, bbudget

    def factory(**kw):
        # the diagnostic oracle's hook: only the screen harness passes it
        # (`make_bot(name, seed=, oracle_deal=)`); the game server never does,
        # so an oracle name refuses to build there (`_check_oracle_hook`)
        oracle_deal = kw.get("oracle_deal")
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
                               world_history_legal=config.world_history_legal,
                               world_history_draw=config.world_history_draw,
                               belief_worlds=config.belief_worlds,
                               belief_capacity=config.belief_capacity,
                               belief_checkpoint=belief_checkpoint,
                               belief_sha256=config.belief_sha256,
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
                               finish_lead_admission=config.finish_lead_admission,
                               exact_lead_endgame=config.exact_lead_endgame,
                               exact_lead_tie_baseline=config.exact_lead_tie_baseline,
                               exact_lead_policy_first=config.exact_lead_policy_first,
                               exact_deep_cards=config.exact_deep_cards,
                               exact_lead_max_seconds=config.exact_lead_max_seconds,
                               exact_deep_max_nodes=config.exact_deep_max_nodes,
                               exact_follow=config.exact_follow,
                               exact_follow_max_nodes=config.exact_follow_max_nodes,
                               exact_follow_solver=config.exact_follow_solver,
                               exact_follow_max_cards=config.exact_follow_max_cards,
                               exact_world_subset=config.exact_world_subset,
                               doomed_throw_reselect=config.doomed_throw_reselect,
                               doomed_throw_reselect_exact_guard=config.doomed_throw_reselect_exact_guard,
                               leaf_greedy_finish=config.leaf_greedy_finish,
                               leaf_greedy_finish_exact_skip=config.leaf_greedy_finish_exact_skip,
                               leaf_greedy_deadline_ms=config.leaf_greedy_deadline_ms,
                               leaf_greedy_top=config.leaf_greedy_top,
                               wide_lead_k=config.wide_lead_k,
                               lead_confirm=config.lead_confirm,
                               value_declare=config.value_declare,
                               value_declare_worlds=config.value_declare_worlds,
                               value_declare_margin=config.value_declare_margin,
                               value_declare_every_first=config.value_declare_every_first,
                               value_declare_served_bury=config.value_declare_served_bury,
                               value_declare_pass_worlds=config.value_declare_pass_worlds,
                               value_declare_wait=config.value_declare_wait,
                               declare_asap_first=config.declare_asap_first,
                               leaf_policy_first_trick=config.leaf_policy_first_trick,
                               bury_wide_value=bury_wide_value, bury_wide_k=bury_wide_k,
                               bury_wide_swaps=bury_wide_swaps,
                               bury_two_stage=bury_two_stage,
                               bury_kitty_charge=bury_kitty_charge,
                               oracle_worlds=config.oracle_worlds,
                               oracle_deal=oracle_deal,
                               oracle_mix_k=config.oracle_mix_k,
                               oracle_pin_q=config.oracle_pin_q),
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
    ``_REFUSAL_EVENT_COMPLETE`` / ``_WORLD_HISTORY_LEGAL`` / ``_WORLD_HISTORY_DRAW`` /
    ``_BELIEF_WORLDS`` / ``_BELIEF_CAPACITY`` / ``_TIEBREAK_POINTS`` / ``_ADAPTIVE_K`` / ``_LEAD_ANCHOR`` / ``_LEAD_TIEBREAK_PRIOR`` /
    ``_DOOMED_THROW_SWAP`` / ``_SMALL_JOKER_GUARD`` / ``_ADAPTIVE_WORLDS`` / ``_ADAPTIVE_WORLDS_LEADS`` /
    ``_WIDE_LEAD_ADMISSION`` / ``_FINISH_LEAD_ADMISSION`` / ``_EXACT_LEAD_ENDGAME`` /
    ``_EXACT_LEAD_TIE_BASELINE`` / ``_EXACT_LEAD_POLICY_FIRST`` / ``_DOOMED_THROW_RESELECT`` /
    ``_DOOMED_THROW_RESELECT_EXACT_GUARD`` (needs ``_DOOMED_THROW_RESELECT=1`` and
    ``_EXACT_LEAD_ENDGAME=1``) / ``_LEAF_GREEDY_FINISH`` (refused with ``_TREE_SIMS``,
    ``_ADAPTIVE_WORLDS`` or ``_ADAPTIVE_WORLDS_LEADS``) / ``_LEAF_GREEDY_FINISH_EXACT_SKIP``
    (needs ``_LEAF_GREEDY_FINISH=1`` and ``_EXACT_LEAD_ENDGAME=1`` or ``_EXACT_FOLLOW=1``) /
    ``_VALUE_DECLARE`` /
    ``_VALUE_DECLARE_EVERY_FIRST`` / ``_VALUE_DECLARE_SERVED_BURY`` / ``_VALUE_DECLARE_PASS_WORLDS``
    / ``_VALUE_DECLARE_WAIT`` / ``_DECLARE_ASAP_FIRST`` /
    ``_LEAF_POLICY_FIRST_TRICK``
    / ``_EXACT_FOLLOW`` and its ``_EXACT_FOLLOW_MAX_NODES`` /
    ``_EXACT_FOLLOW_SOLVER`` / ``_EXACT_FOLLOW_MAX_CARDS`` DEV knobs, the exact lead
    stage's ``_EXACT_LEAD_MAX_SECONDS`` (needs ``_EXACT_LEAD_ENDGAME=1``) and
    ``_EXACT_DEEP_MAX_NODES`` (needs ``_EXACT_DEEP_CARDS``) DEV caps
    / ``_ORACLE_WORLDS`` rule flags (``0`` or ``1`` only; unset or empty is off) and the
    ``_VALUE_DECLARE_WORLDS`` / ``_VALUE_DECLARE_MARGIN`` parameters (refused unless
    ``_VALUE_DECLARE=1``), as keyword arguments for `pv_registry_entries`.
    ``_VALUE_DECLARE_EVERY_FIRST=1``, ``_VALUE_DECLARE_PASS_WORLDS=1`` or ``_VALUE_DECLARE_WAIT=1`` without
    ``_VALUE_DECLARE=1`` and ``_DECLARE_ASAP_FIRST=1`` with it are refused there (`recipe_payload`); ``_LEAF_POLICY_FIRST_TRICK=1`` without
    ``_VALUE_DECLARE=1`` or a hybrid/value ``_BURY_ARM`` is refused there too
    (`_check_leaf_policy_effect`), and ``_VALUE_DECLARE_SERVED_BURY=1`` without
    ``_VALUE_DECLARE=1`` or the wide chooser (`_check_served_bury_effect`).  ``_BURY_WIDE_VALUE`` (``0`` or ``1``; needs ``_BURY_ARM``,
    a hybrid/value one) and its ``_BURY_WIDE_K`` cap (an int in [2, 128]) and
    ``_BURY_WIDE_SWAPS`` depth (``1`` or ``2``; both refused unless ``_BURY_WIDE_VALUE=1``)
    select the wide value-only bury chooser (module docstring), and ``_BURY_TWO_STAGE``
    (``0`` or ``1``; needs ``_BURY_WIDE_VALUE=1``) with its ``_BURY_TWO_STAGE_TOP`` /
    ``_WORLDS`` / ``_TRICKS`` / ``_MARGIN`` / ``_Z`` / ``_SECONDS`` parameters (each refused
    unless ``_BURY_TWO_STAGE=1``) its second stage, and ``_BURY_KITTY_CHARGE`` (``0`` or
    ``1``; needs ``_BURY_WIDE_VALUE=1``) its kitty charge.
    ``_ORACLE_WORLDS=1`` (the diagnostic) registers a name whose factory REFUSES to build
    without the screen harness's ``oracle_deal`` hook (`_check_oracle_hook`), so the game
    server can never serve it; `api.server` refuses the flag at import besides.  Its
    soft variants ``_ORACLE_MIX_K`` (an int in [1, W-1]) and ``_ORACLE_PIN_Q`` (a whole
    percentage in (0, 1)) take the same refusals; unset, empty or ``0`` is off."""
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
    belief_ckpt = env.get(ENV_PREFIX + "BELIEF_CKPT")
    belief_sha = env.get(ENV_PREFIX + "BELIEF_SHA256")
    if bool(belief_ckpt) != bool(belief_sha):
        raise PVSearchPolicyError("SHENGJI_PV_BELIEF_CKPT and SHENGJI_PV_BELIEF_SHA256 go together")
    if belief_ckpt:
        if len(belief_sha) != 64:
            raise PVSearchPolicyError("SHENGJI_PV_BELIEF_SHA256 must be the belief package's full sha256")
        recipe.update(belief_checkpoint=belief_ckpt, belief_sha256=belief_sha)
    # the belief log flag is no part of the recipe (no name or digest reads it);
    # a malformed value still refuses here, before any bot is built
    belief_log_enabled(env)
    # nor are the latency switches; the same early refusal
    latency_switches(env)
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
    # Exact-follow is DEV-only but still travels through the real factory.  Its
    # parameters are explicit: silently accepting one while the rule is off
    # would make the requested identity meaningless.
    follow_params = {
        "EXACT_FOLLOW_MAX_NODES": "exact_follow_max_nodes",
        "EXACT_FOLLOW_SOLVER": "exact_follow_solver",
        "EXACT_FOLLOW_MAX_CARDS": "exact_follow_max_cards",
    }
    for suffix, key in follow_params.items():
        raw = env.get(ENV_PREFIX + suffix)
        if raw in (None, ""):
            continue
        if not recipe.get("exact_follow"):
            raise PVSearchPolicyError(
                f"{ENV_PREFIX}{suffix} needs {ENV_PREFIX}EXACT_FOLLOW=1")
        if key == "exact_follow_solver":
            recipe[key] = raw
        else:
            try:
                recipe[key] = int(raw)
            except ValueError:
                raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} is not an int: {raw!r}") from None
    follow_config = PVSearchConfig(
        checkpoint_sha256=recipe["sha256"],
        exact_follow=bool(recipe.get("exact_follow", False)),
        exact_follow_max_nodes=recipe.get("exact_follow_max_nodes", 250_000),
        exact_follow_solver=recipe.get("exact_follow_solver", "reference"),
        exact_follow_max_cards=recipe.get("exact_follow_max_cards", 4),
    )
    _check_exact_follow_params(follow_config)
    # the soft oracle's parameters (diagnostic; module docstring): unset, empty
    # or 0 is off; refused by `api.server` at import and, without the
    # harness's hook, by the registry factory
    for suffix, key in ORACLE_SOFT_PARAMS.items():
        raw = env.get(ENV_PREFIX + suffix)
        if raw in (None, "", "0"):
            continue
        try:
            value = int(raw) if key == "oracle_mix_k" else float(raw)
            if key == "oracle_mix_k":
                soft_oracle.check_mix_k(value)
            else:
                soft_oracle.check_pin_q(value)
        except (ValueError, soft_oracle.SoftOracleConfigError) as exc:
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix}={raw!r}: {exc}") from None
        if value:
            recipe[key] = value
    # the greedy finish's deadline in seconds: unset, empty or 0 is off
    raw = env.get(ENV_PREFIX + LEAF_GREEDY_DEADLINE_ENV)
    if raw not in (None, "", "0"):
        try:
            seconds = float(raw)
        except ValueError:
            raise PVSearchPolicyError(
                f"{ENV_PREFIX}{LEAF_GREEDY_DEADLINE_ENV} is not a number: {raw!r}") from None
        ms = round(seconds * 1000) if math.isfinite(seconds) else None
        if ms is None or abs(seconds * 1000 - ms) > 1e-6:
            raise PVSearchPolicyError(
                f"{ENV_PREFIX}{LEAF_GREEDY_DEADLINE_ENV} must be seconds in whole ms: {raw!r}")
        recipe["leaf_greedy_deadline_ms"] = int(ms)
        _check_leaf_greedy_deadline(PVSearchConfig(
            checkpoint_sha256=recipe["sha256"],
            leaf_greedy_finish=bool(recipe.get("leaf_greedy_finish", False)),
            leaf_greedy_deadline_ms=int(ms)))
    # the finish's top-m restriction (unset, empty or 0 is off) and the lead
    # admission width (unset or empty is the default); each needs its rule
    for suffix, key, needs, needs_env in (
            (LEAF_GREEDY_TOP_ENV, "leaf_greedy_top", "leaf_greedy_finish", "LEAF_GREEDY_FINISH"),
            (WIDE_LEAD_K_ENV, "wide_lead_k", "wide_lead_admission", "WIDE_LEAD_ADMISSION")):
        raw = env.get(ENV_PREFIX + suffix)
        if raw in (None, "") or (raw == "0" and key == "leaf_greedy_top"):
            continue
        if not recipe.get(needs):
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} needs {ENV_PREFIX}{needs_env}=1")
        try:
            value = int(raw)
        except ValueError:
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} is not an int: {raw!r}") from None
        probe = PVSearchConfig(checkpoint_sha256=recipe["sha256"], **{needs: True, key: value})
        (_check_leaf_greedy_top if key == "leaf_greedy_top" else _check_wide_lead_k)(probe)
        recipe[key] = value
    # the held-out lead confirmation's pool width: unset, empty or 0 is off
    raw = env.get(ENV_PREFIX + LEAD_CONFIRM_ENV)
    if raw not in (None, "", "0"):
        try:
            value = int(raw)
        except ValueError:
            raise PVSearchPolicyError(f"{ENV_PREFIX}{LEAD_CONFIRM_ENV} is not an int: {raw!r}") from None
        lo, hi = LEAD_CONFIRM_K_RANGE
        if not lo <= value <= hi:
            raise PVSearchPolicyError(f"{ENV_PREFIX}{LEAD_CONFIRM_ENV} must be an int in [{lo}, {hi}]")
        recipe["lead_confirm"] = value
    # the exact stages' world subset: unset, empty or 0 is off
    raw = env.get(ENV_PREFIX + EXACT_WORLD_SUBSET_ENV)
    if raw not in (None, "", "0"):
        try:
            recipe["exact_world_subset"] = int(raw)
        except ValueError:
            raise PVSearchPolicyError(
                f"{ENV_PREFIX}{EXACT_WORLD_SUBSET_ENV} is not an int: {raw!r}") from None
    # the deeper exact rule's parameter: unset, empty or 0 is off
    for suffix, key in EXACT_DEEP_PARAM.items():
        raw = env.get(ENV_PREFIX + suffix)
        if raw in (None, "", "0"):
            continue
        try:
            value = int(raw)
        except ValueError:
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} is not an int: {raw!r}") from None
        _check_exact_deep_cards(value)
        recipe[key] = value
    # the exact lead stage's DEV caps: unset or empty is the default; a value is
    # refused unless its stage is on and the value is in range
    for suffix, key in EXACT_LEAD_CAP_PARAMS.items():
        raw = env.get(ENV_PREFIX + suffix)
        if raw in (None, ""):
            continue
        needs = ("EXACT_LEAD_ENDGAME=1" if key == "exact_lead_max_seconds"
                 else "EXACT_DEEP_CARDS")
        if not recipe.get("exact_lead_endgame" if key == "exact_lead_max_seconds"
                          else "exact_deep_cards"):
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} needs {ENV_PREFIX}{needs}")
        try:
            value = float(raw) if key == "exact_lead_max_seconds" else int(raw)
        except ValueError:
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} is not a number: {raw!r}") from None
        recipe[key] = value
    _check_exact_lead_caps(PVSearchConfig(
        checkpoint_sha256=recipe["sha256"],
        exact_lead_endgame=bool(recipe.get("exact_lead_endgame", False)),
        exact_deep_cards=recipe.get("exact_deep_cards", 0),
        **{key: recipe[key] for key in EXACT_LEAD_CAP_PARAMS.values() if key in recipe}))
    # the declaration rule's parameters: only with the rule on
    for suffix, key in VALUE_DECLARE_PARAMS.items():
        raw = env.get(ENV_PREFIX + suffix)
        if raw in (None, ""):
            continue
        if not recipe.get("value_declare"):
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} needs {ENV_PREFIX}VALUE_DECLARE=1")
        try:
            value = int(raw) if key == "value_declare_worlds" else float(raw)
        except ValueError:
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} is not a number: {raw!r}") from None
        _check_value_declare_params(value if key == "value_declare_worlds"
                                    else VALUE_DECLARE_DEFAULTS["value_declare_worlds"],
                                    value if key == "value_declare_margin"
                                    else VALUE_DECLARE_DEFAULTS["value_declare_margin"])
        recipe[key] = value
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
    # the wide value-only chooser (a bury setting): 0/1, and its cap only with it on
    for suffix, key in BURY_WIDE_VALUE_FLAG.items():
        raw = env.get(ENV_PREFIX + suffix)
        if raw in (None, ""):
            continue
        if raw not in ("0", "1"):
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} must be 0 or 1, not {raw!r}")
        if raw == "1":
            if not arm:
                raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix}=1 needs {ENV_PREFIX}BURY_ARM")
            recipe[key] = True
    for suffix, key in BURY_WIDE_VALUE_PARAM.items():
        raw = env.get(ENV_PREFIX + suffix)
        if raw in (None, ""):
            continue
        if not recipe.get("bury_wide_value"):
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} needs {ENV_PREFIX}BURY_WIDE_VALUE=1")
        try:
            recipe[key] = int(raw)
        except ValueError:
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} is not an int: {raw!r}") from None
        _check_wide_k(recipe[key])
    for suffix, key in BURY_WIDE_SWAPS_PARAM.items():
        raw = env.get(ENV_PREFIX + suffix)
        if raw in (None, ""):
            continue
        if not recipe.get("bury_wide_value"):
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} needs {ENV_PREFIX}BURY_WIDE_VALUE=1")
        if raw not in ("1", "2"):
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} must be 1 or 2, not {raw!r}")
        recipe[key] = int(raw)
    # the wide chooser's second stage: 0/1, and its parameters only with it on
    two_stage = False
    for suffix in BURY_TWO_STAGE_FLAG:
        raw = env.get(ENV_PREFIX + suffix)
        if raw in (None, ""):
            continue
        if raw not in ("0", "1"):
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} must be 0 or 1, not {raw!r}")
        if raw == "1":
            if not recipe.get("bury_wide_value"):
                raise PVSearchPolicyError(_BURY_TWO_STAGE_REQUIRES)
            two_stage = True
    params = {}
    for suffix, field in BURY_TWO_STAGE_PARAMS.items():
        raw = env.get(ENV_PREFIX + suffix)
        if raw in (None, ""):
            continue
        if not two_stage:
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} needs {ENV_PREFIX}BURY_TWO_STAGE=1")
        try:
            params[field] = float(raw) if field in ("margin", "z", "seconds") else int(raw)
        except ValueError:
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} is not a number: {raw!r}") from None
    if two_stage:
        try:
            recipe["bury_two_stage"] = BuryTwoStageConfig(**params)
        except BuryPolicyError as exc:
            raise PVSearchPolicyError(str(exc)) from None
    # the wide chooser's kitty charge: 0/1, only with the chooser on
    for suffix, key in BURY_KITTY_CHARGE_FLAG.items():
        raw = env.get(ENV_PREFIX + suffix)
        if raw in (None, ""):
            continue
        if raw not in ("0", "1"):
            raise PVSearchPolicyError(f"{ENV_PREFIX}{suffix} must be 0 or 1, not {raw!r}")
        if raw == "1":
            if not recipe.get("bury_wide_value"):
                raise PVSearchPolicyError(_BURY_KITTY_CHARGE_REQUIRES)
            recipe[key] = True
    return recipe
