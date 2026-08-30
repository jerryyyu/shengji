# Gameplay decision stack — adversarial review synthesis (2026-08-23)

STATUS: synthesis of 4 independent verifiers (V1 source-mechanism, V2 transcript
stats, V3 decision-record corpus, V4 objective/harness) and 5 attack lenses
(A1 statistics/power, A2 exemplar/branch-trace, A3 objective-semantics,
A4 program/process, A5 cost/forward-compat) applied to
`tmp/gameplay/FINDINGS.md`. Source citations are file:line in the read-only
worktree at `tmp/gp-src-68f9/server/` (origin/main); transcripts are
`/Users/jerryyu/Projects/shengji/logs/*.jsonl`. Every computed number is
labeled (recomputed) by its producer; every judgment (assessment). **This
document adopts nothing and selects nothing.** All adoption goes through the
standing bars, restated in full in section 3.

Bottom line (assessment): the code mechanisms (F1/F3/F8) and the exemplar
record (F2) survived verification, but the harm case collapsed to a bounded
1.2%-of-decisions shape with no measured round-level effect; two findings were
refuted outright (F9, F6's "never dueled"); and the six-layer design needs
major revision — its confidence signal instruments the wrong generator, its
widening arm is a near-null treatment, its gating spec manipulates a dead
parameter, and its two >=55% duels are unpowerable as staged.

---

## 1. Verdict table F1–F12

| # | Verdict | Decided by | Disposition |
|---|---------|-----------|-------------|
| F1 | CONFIRMED, with caveat | V1 | The bare-point-lead mechanism is exact: last-resort branch heuristic.py:142-146, `avoid_points` is a sort key not a filter (heuristic.py:338-339). Caveat: `HeuristicBot._lead` is the ROLLOUT policy (mcbot.py:226); the incumbent candidates[0] comes from `SmartBot._lead` (mcbot.py:1330), whose own last-resort tails (smart.py:415-422) inherit the same non-filtering `_lowest` — so the mechanism holds for the incumbent but F1's branch taxonomy does not describe the incumbent generator. |
| F2 | CONFIRMED as record; REVISED as harm evidence | V3 (record); A1 + V3 (interpretation) | Every figure in the TZGK r6 seat-2 record matches (candidates, means, indices, gap 0.25 / se 1.379 / 300 worlds, reason). Revision: the 3.5-pt selection-fold "preference" for S3 is below the expected max-gap under pure noise across 9 candidates (~6.4 pts, A1 recomputed); the 300-world fold measured indifference (z=0.18). F2 is a mechanism illustration plus one bad realized outcome, not measured harm. The F2 harm shape is bounded corpus-wide at 26 of 2,257 decisions (~1.2%; 16 leads, 10 follows) (V3 recomputed, independently matched by A1). |
| F3 | REVISED | V1 | Incumbent-at-index-0 with no confidence signal: confirmed on every conservative path. Revision: "same MARGIN=5 + report-LCB protection" is wrong for the live champion — REPORT_FOLD_WORLDS=300 (registry.py:147-153) makes every contested decision return inside the report block (mcbot.py:463-500); the MARGIN comparison (mcbot.py:502-528) is unreachable, computed and logged but never compared. Live protection = TRACTOR_LOCK (mcbot.py:281-285, stronger: no search at all) + report-LCB gate (t=1.70 at mcbot.py:188, REPORT_MIN_GAIN=0.0). Zero margin-comparison reasons in all 2,257 logged decisions (A3 recomputed). Core point (no differentiation among searched picks) stands. |
| F4 | REVISED | V2 + A1 | Corpus counts exact (56/185/2,978, 21 truncated; V2 recomputed). All rates reproduce only under round_start seat attribution, which mislabels ~650 bot-engine autoplays in human-registered seats (~15% contamination); play-level attribution shifts every figure slightly and the headline (feeding complaint is an artifact) survives strengthened. Killed within F4: the 54.4/54.4 parity (aggregation artifact — "non-point singles" mixes aces at 80.6% with junk at 48.8%; bare-10 at 54.2% is ns vs junk, wrong direction for harm); the 18.7-vs-7.0 contrast (10 of the 18.7 is the led card; marginal concession 8.7 vs 7.2, and bare-K is identical at 8.7); "raw" is value-weighted while "controlled" is per-play (definitional inconsistency); the human baseline is effectively 2–4 people with no clustered SEs (A1 recomputed). 85% of evaluable bot feeds were forced; discretionary feed rate bot 2.3% vs human 1.8% (A1 recomputed). |
| F5 | CONFIRMED | All four verifiers left it untouched; A2 replay strengthens | No round-level counterfactual was measured, and the exemplar round was in fact WON by seat 2's team despite the 20-pt trick (A2 recomputed from round_end). F5's refusal to convert trick tables into round harm is the discipline that held. See Unresolved. |
| F6 | REVISED | V1/V4 (parts 1–2), V4 REFUTED part 3 | Part 1 confirmed and strengthened: raw `float(clone.attacker_points)` (mcbot.py:1897); the bracket objective (_score, mcbot.py:925-941) is wired at every call site — a single-flag arm, not dead code. Part 2 revised: `deal=±0.5` is NOT an engine rule (engine/game.py:58,62 moves next_banker, scores nothing — an uncalibrated modeling choice); the `min(3,…)` cap diverges from the engine's uncapped `(p-80)//40` at p>=240 (kitty-reachable); within-bracket the 0.2 factor compresses differences 5x, so MARGIN/EPS semantics are NOT uniformly preserved (V4 recomputed, exhaustive p=0..400). Part 3 REFUTED: LEVEL_OBJECTIVE has a recorded duel tie ("59% vs 62% ref | tie", AI_POLICIES.md:491; grouped as "did not establish gains", AI_POLICIES.md:345) and an explicit 08-12 STOP ("A full matched pilot is not justified", JOBS.md:52, PR #47). Defensible residue: never dueled on the current report-LCB + wide-ballot stack. |
| F7 | REVISED | V4 | True as written for tournament.py:46-90 (binary wins only) — but that is the legacy Elo pool tool. The gating harness is evaluation.py ("THE evaluator", evaluation.py:1), which already records paired per-seed level utility (evaluation.py:154, 167-191). Genuine gaps: raw attacker_points margins absent from the per-round rec (evaluation.py:152-155 despite log.attacker_points in scope at :139), and `max(1, level_change)` collapses attacker gain-0 vs gain-1 — the 120 cliff is invisible to the recorded metric. |
| F8 | CONFIRMED, scope-bounded | V1 (mechanism); V3 + A1 (scope) | Call order confirmed: point-shy runs inside `_pick_index` (mcbot.py:533-544), the report gate runs after and restores candidates[0] with no point comparison (mcbot.py:494-497). Bound: 65.6% of the 703 gate restores had report gap<=0 — the gate was rejecting non-replicating 30-world winners (its job, variance reduction), not protecting incumbents. The F2 harm shape is 26 instances (~1.2% of decisions). Any fix targets the tie-with-point-risk subset, not the override reason. |
| F9 | REFUTED | V1; A2 closed the residual loophole | WIDE_LEAD_BALLOT=True (ADOPTED 62%, mcbot.py:150-153) already generates every trump tractor/pair and the top trump single (mcbot.py:1356-1366), plus the lowest trump single unconditionally (mcbot.py:1379-1381); F2's own ballot contained BJ priced at -70.67. TRUMP_BALLOT is nearly a no-op under dedup (mcbot.py:1319-1321). Cap-eviction residue closed empirically: 19/596 lead ballots hit the 14-cap, 0 lost all trump candidates (A2 recomputed). Survives: the -4%-three-times comment record (mcbot.py:207-210) and the unmeasured marginal flag. Per-position trump pricing happens in production on every uncapped lead. |
| F10 | CONFIRMED, strengthened | V1; A2 replay | Both punishment mechanisms exist in rollouts (heuristic.py:169-175 cheapest-winner take, broader than claimed; heuristic.py:164-167 partner point-dump). The exemplar replay shows rollouts contained BOTH the punishment that made H10 bad AND the rescue line that made holding it good, and the raw objective was well calibrated (E[attacker pts | H10]≈67.7 vs actual 65) — the failure was search topology, not modeling (A2 recomputed + assessment). Nuance: partner-dump fires only on a strong partner winner or last seat. |
| F11 | REVISED | A2 | Frame inverted: seat 2 was the DEFENDING BANKER with a locked 15-trump hand and the team WON the round (attackers 65; defenders +1 level) — the decision was concession control inside a won round, not "mostly-lost" (A2 recomputed from TZGK.jsonl). The blunder chain starts at the BURY (kept doomed H10, buried HQ; the written KITTY_POINT_POLICY locked-hand rule, smart.py:43-46, meets its own trigger here) — which no layer L-A..L-F touches. The bracket-objective hope is quantitatively backwards in this state (bracket scoring DAMPS per-world discrimination, ratio ~0.55–0.73 under stated assumptions; A2 recomputed). The binding constraint is search topology: BJ never reached a 300-world comparison. |
| F12 | REVISED | A1 | The salience/experience axis survives. The supporting stat is wrong: the TZGK night had 4 bot-made bare-10 leads with 2 won (play-level; 2/3 under round_start attribution — no convention yields 3/4), both losses conceding 20 pts (A1 recomputed). The reassurance claim is falsified; the salience claim is, if anything, supported. |

---

## 2. Unified design, as revised by surviving attacks

Layer by layer. Every fatal/serious attack is either incorporated (⊕) or
rebutted (⊖) with basis. Everything here is design revision, not adoption.

### L-A GENERATION — respecified: one candidate, not four

⊕ FATAL (A2, A5, A4, convergent): three of the four structured candidates are
already generated by the production wide ballot and dedup to no-ops — lowest
trump unconditionally (mcbot.py:1379-1381), highest trump via the wide loop's
top single for s=TRUMP (mcbot.py:1356, 1365-1366), lowest non-point per plain
suit (mcbot.py:1378); `add()` dedups (mcbot.py:1319-1321). In the F2 record
itself all four roles were already on the ballot (S3, BJ, D9/C9, CQ) — L-A
would have added zero candidates to the hand that motivates the design.
⊕ FATAL premise (V1's F9 refutation): "trump candidates priced only when
unsure" describes something already happening on every uncapped lead.
⊖ REBUTTED (A5, strengthens): the Q7 cost objection fails — the report fold is
77.0% of the rollout budget (recomputed); +4 candidates is +0.82% fleet-wide
worst case; the +7% latency precedent predates the report fold and is stale.
Cost is not the reason to shrink L-A; redundancy is.

REVISED L-A: (a) at most ONE structured addition — highest non-point single,
only when a suit's top single is a point card (the sole non-redundant member,
A5); (b) the substantive menu-widening lane is V3_LEAD_SINGLES mid-rank
singles — already written including the leave-behind-shape equivalence fix
(mcbot.py:1431-1459), motivated by the ballot audit's 15.5% off-ballot human
leads, 55 of them middle-rank singles (mcbot.py:1418-1425) — fired only in
unsure states; (c) MANDATORY dose witness before sizing anything
(prove-the-check-can-fail): exhibit at least one decision record where the new
candidate appears, is absent from the champion ballot, and survives the
LEAD_MAX_CANDIDATES=14 slice (mcbot.py:1463-1465).

⊕ SERIOUS (A5, unresolved by widening alone): new candidates reach play only
through the single challenger slot, nominated by the noisy 30-world argmax
(corpus mean paired selection SE 2.52, p95 5.48, vs mean ballot spread 7.5;
A5 recomputed). Widening without a selection-reliability change enters
candidates into a lottery. See L-D budget options.

### L-B PRIOR CONFIDENCE — respecified: right generator, data not control flow

⊕ FATAL (A2, A4, A5, convergent — the review's single strongest result): L-B
instruments the wrong policy. The incumbent candidates[0] is `SmartBot._lead`'s
pick (mcbot.py:1330); `HeuristicBot._lead` is only the rollout policy
(mcbot.py:226). The branch set {tractor, ace-pair, lone-ace, high-pair,
last-resort} is HeuristicBot's (heuristic.py:104-146); SmartBot's is different
(safe-throw / control-leads / its own last-resort tails, smart.py:227-422).
F2's own incumbent H10 came from the CONTROL_LEADS short-suit-emptying branch
(smart.py:394-396) — outside the taxonomy under BOTH possible wirings, so the
design as written leaves its flagship complaint hand unchanged (A2's branch
trace, deterministic from code + the F2 record).

REVISED L-B: provenance defined on `SmartBot._lead`'s actual branches.
"Unsure" = (i) the last-resort tails (smart.py:415-422); (ii) a
short-suit-emptying lead whose only legal card carries points (covers F2 by
construction); (iii) — revising Q3's "no for v1" (⊕ SERIOUS, A2 coverage
attack) — a statistical trigger: incumbent selection deficit > 2× selection
SE, computed from fields already in every mc-decision-v2 record. The
statistical trigger is what covers the 441 follow-restores and
confident-branch blunder classes (memory-free ace leads, the KK-with-aces-live
high-pair gate at heuristic.py:140, TRACTOR_LOCK's unexamined point tractors)
that a lead-only branch label certifies blindly.
⊕ FORWARD-COMPAT (A5): the tag is carried as a data field on the decision
record (opaque string), never as a control-flow gate key; the statistical
predicate is generator-agnostic and survives a future learned generator.

### L-C OBJECTIVE — conditionally retained as a changed-stack retest with recalibration

⊕ REFUTED premise (V4): "apparently never dueled" is false — recorded tie
(AI_POLICIES.md:491) and 08-12 STOP (JOBS.md:52). If arm (iii) runs it must be
written as a changed-stack retest (report-LCB and WIDE_LEAD_BALLOT postdate
the tie record), citing both records, with the prior looks counted in the
adoption analysis and the supersession recorded where the STOP lives (A3, A4).
⊕ FATAL-if-unfixed (A3): eps takeover — POINT_SHY_EPS=2.0 on the 0.2-compressed
axis is a ~10-raw-point tie window, covering the entire ballot in ~78% of
decisions (upper bound; A3 recomputed) — arm (iii) unfixed measures
objective-switch + untuned eps jointly. Fix inside the arm definition:
eps_scaled = 0.4 (or an se-unit window), declared and logged per decision.
⊕ SERIOUS (A3): level-blindness is constructible harm, not just a caveat — a
defender-at-K scenario exists where the bracket objective picks the strictly
worse candidate and the 300-world LCB gate CONFIRMS the error (recomputed
against the actual _score; the gate guards variance, not objective
mis-specification). Half-fix available with NO plumbing: the defending team's
level IS `rnd.trump_rank`; _score can truncate defender-side brackets today.
Attacker level requires passing Game state.
⊕ SERIOUS (A2): pre-register the exemplar prediction — bracket scoring should
change the S3/H10/BJ ordering in the TZGK r6 state; the damping arithmetic
predicts it will not. If it does not, the arm's mechanism story is dead before
a duel spends a box.
⊕ MINOR (A3, V4): uncap the bracket term (engine is uncapped, kitty-reachable
p>=240); calibrate or expose the invented deal=±0.5 weight. A registry entry
must be created (nothing sets LEVEL_OBJECTIVE today). Latent: the bury-path
MARGIN at mcbot.py:1065 is alive and unscaled under any future
L-C + MC_BURY composition.
⊖ REBUTTED (A3, strengthens): "the 0.2*p term never clears the gate far from a
cliff" is false — far from cliffs the report statistic is scale-invariant
(identical block/override behavior); near cliffs the gate still blocks unless
the challenger nets ~>=3 bracket-crossing worlds of 300 (recomputed algebra).
⊖ REBUTTED (A3, strengthens, vs V4): the claimed LEVEL_OBJECTIVE +
EXACT_ENDGAME inconsistency is overstated — _score is strictly monotone in p,
commutes with per-world minimax, and is applied per world before averaging.

### L-D GATING — respecified in report-rule terms; minimal fix promoted to arm zero

⊕ SERIOUS (A2, A3, A4, convergent): both halves of L-D's spec manipulate the
dead MARGIN parameter (see F3). Respecified: confident → REPORT_RULE="lcb"
unchanged; unsure → REPORT_RULE="mean" plus a report-stage point-shy tie-break
at |gap| <= k*se. All MARGIN language deleted from the design. Note the
registered-but-never-dueled `mc-s0-report-mean` (registry.py:140-146) makes
this an open lane, not a settled one.
⊕ STRENGTHENS (A2) — ARM ZERO: a single unconditional report-stage tie-break
("when |gap| <= k*se at the 300-world fold, play whichever of
{incumbent, challenger} risks fewer points", ~10 lines at the restore site
mcbot.py:494-497, reusing the POINT_SHY concept) fixes the exemplar and the
entire verified 26-case harm class with no confidence signal, no new
candidates, no objective change. Corpus flip table: 10 worse / 17 better / 79
equal on point risk among the 106 gap>0 lead restores (A2 recomputed). It runs
FIRST; if it clears, re-derive whether L-A/L-B/L-D still have a job. Caveat
carried: "points at risk" ignores trump-length cost, so it tilts toward
spending trump singles — same stratified drain report as arm (ii).
⊕ SERIOUS (A2): trump-drain resurrection is the dominant content of the unsure
branch — 50.0% of gate-restored lead challengers are all-trump; the exemplar
challenger S3 is literally a banker cheap-trump drain (TRUMP_DRAIN_V2,
"measured: hurts", smart.py:67; -4pt rejected, AI_POLICIES.md:468); the 55
sub-LCB drain flips are priced by a rollout policy that never ducks a winnable
trump-led trick (heuristic.py:169-175). Guard in v1: keep the LCB for
all-trump challengers in the unsure branch, relax only non-trump; pre-register
a stratified (drain/cash/junk) report.
⊕ SERIOUS (A2, A5): the two-candidate report topology survives inside "trust
the fold" — the challenger is nominated by the 30-world argmax, so the true
best frequently never reaches 300 worlds (in F2, S3 vs BJ vs DK was never
compared at precision). Budget options, one to be chosen and stated before any
duel: successive halving over the ballot on shared worlds; raise N_DET for the
unsure subset only (~5% of searched decisions); or a budgeted k-challenger
fold (+600 rollouts each, +77%/decision).
⊕ WITNESSES (A4, prove-the-check-can-fail): (i) confident path byte-identical
to the champion on a decision-record corpus; (ii) unsure path flips TZGK r6 s2
H10→S3; (iii) a deliberately broken variant proving each witness can fail.
⊖ REBUTTED (A2, strengthens): "the incumbent gate is the villain" — the gate
does real epistemic work: 56% of raw 30-world lead disagreements were
wrong-or-unproven at 300 worlds; gateless argmax would routinely play noise.
The burden is the fold's two flaws (challenger-selection noise, unpriced
rollout bias), not gate removal.

### L-E TELEMETRY — respecified as offline analysis first; prod patch under witness protocol

⊕ SERIOUS (A5): ~90% redundant — everything proposed except the branch tag is
already in every mc-decision-v2 record (candidates, means, paired_se,
raw_winner_index = would-override, played_index, report gap/se/statistic;
mcbot.py:416-455, 482-489); the verifiers' entire 703-override scan ran on
existing telemetry. Stage 0 becomes an OFFLINE analysis job on the 2,257
records — zero prod change, immediately powered.
⊕ SERIOUS (A4): "no policy change" is currently unwitnessed — the branch field
requires the L-B signature change; RNG-stream perturbation silently changes
play (the exact seam PR #39's save/restore-RNG fix exists for); identity
hashes in the record change under any patch. Any prod telemetry patch ships
only with: PR review, replay witness (identical decision stream AND
post-decision RNG state, telemetry on vs off), a deliberately-broken variant,
a schema bump (mc-decision-v3), and a predeclared corpus cut date for all
transcript analyses.
⊕ SERIOUS (A5): "thresholds derived from telemetry" cannot be powered from
prod accrual — unsure subpopulation ~5.5/day, harm class ~1.2/day, ~100 days
to n=120 (recomputed); and "unsure" is unspecifiable from logs today
(defensible proxies span 2–4x in firing rate). Derive thresholds from offline
self-play (~34k rollouts/round, laptop-scale; recomputed) and pre-register the
unsure definition before measuring its rate.
Opportunity (A5, recomputed): rng_state is 63.7% of ALL prod log bytes; a
per-decision OS-drawn seed preserves replayability at ~1/600th the size.

### L-F HARNESS — retargeted to evaluation.py

⊕ SERIOUS (V4, A3, A4, A5, convergent): tournament.py is the wrong file — the
legacy Elo pool tool no modern duel runner uses. All current runners import
evaluation.py, which already carries half of L-F (level_utility at :154,
paired_by_seed at :167-191). The incremental patch: add raw `attacker_points`
and UNCLAMPED `level_change` to the per-round rec dict (evaluation.py:152-155;
`max(1, level_change)` currently makes attacker gain-0 vs gain-1 — the 120
cliff — invisible). Fields declared diagnostic-only for this program; all arms
declared to run under evaluation.py; tournament.py untouched.

---

## 3. Staged experiment program, as revised

Adoption bars, restated IN FULL (A4 caught the header's lossy restatement):
preference/policy changes need >=55% round-level duel outcome (n>=120,
work-matched null); menu-widening (adding candidates only) adopts at neutral
AND not clearly negative AND latency acceptable (shengji-adoption-bars.md).
Where an arm below cannot be powered at the standing n, that fact is stated —
the bar-vs-power conflict is surfaced for Jerry, not resolved here.

Stage 0 — OFFLINE analysis (no prod change, no box): run the unsure-definition
and threshold derivation on the existing 2,257 decision records + offline
self-play; pre-register the unsure predicate (branch set on SmartBot._lead +
statistical deficit trigger) before measuring its rate. Any prod telemetry
patch is a separate, review-gated deliverable under the L-E witness protocol.

Stage 1 — evaluation.py measurement patch (diagnostic-only fields; L-F above).
Not a gate for the arms — it gates nothing if skipped, but the arms' analyses
want the margin/bracket fields, so it lands first.

Stage 2 — arms, each with a predeclared comparison graph (A4: one-change-at-a-
time is not preserved by "three arms vs champion"; the PR #39 trigger-matched
two-pass seam is the in-repo template):

- ARM 0 (new, first): unconditional report-stage point-shy tie-break.
  Comparison: vs champion, trigger-matched null (null executes the champion
  decision on the same triggers, S4-style), judged on paired level utility,
  n derived from the measured trigger rate with a predeclared power
  calculation. POWER HONESTY (A1, fatal to the original framing): the
  verified harm class is ~1.2% of decisions; a generous upper bound on the
  round-win delta of the F2-shape fix is ~0.6pp, and detecting that needs
  ~54,000 rounds — no 120-round duel can clear >=55% except by false
  positive (~14% at true zero). The honest justifications available are
  (i) experience/telemetry: reduction in point-card leads from unsure states
  (a salience metric, per F12), under (ii) a round-level NON-INFERIORITY
  check with a pre-registered margin. Whether that combination satisfies the
  preference bar is Jerry's call; this document does not select.
- ARM (i) widen-only: runs ONLY if the stage-0 dose witness shows a real
  marginal candidate set (A2/A5: as originally specified it is a near-null
  treatment and "adopts at neutral" would rubber-stamp dead code — A1: the
  n=120 CI half-width ~9pp cannot distinguish neutral from ~5pp harm).
  If run: full menu bar (neutral AND not clearly negative AND latency
  acceptable), pre-registered non-inferiority margin (e.g., win-rate
  LCB > -2pp needs ~2,400 rounds at 80% power, A1 recomputed), latency
  compared against the 77%-report-fold budget profile, dose logged.
- ARM (ii) trust-when-unsure: RECLASSED (A4) as a confidence-rule scope
  change, not a preference toggle — the protections being narrowed were
  measurement-adopted (MARGIN at 62%, AI_POLICIES.md:486; report-LCB via
  RLCB-C1, whose record explicitly does not authorize confidence-rule
  changes, AI_POLICIES.md:365). It follows the formal packet path:
  treatment vs trigger-matched null on the same mirrored seeds, n from the
  measured unsure-trigger rate (S6 precedent: 7,168 clusters for a
  2.02%-trigger gate, JOBS.md:47-49 — roughly two orders above the staged
  n=120), judged on paired level utility, with the stratified drain report
  (L-D guard) mandatory.
- ARM (iii) LEVEL_OBJECTIVE: runs only as the declared changed-stack retest
  (prior tie + 08-12 STOP cited, looks counted). Arm definition includes
  eps recalibration and per-decision dual-objective logging (A3), a new
  registry entry, the pre-registered exemplar-state prediction (A2), and —
  because F7's own argument says round wins are insensitive to exactly this
  arm's mechanism (A4 caught the self-contradiction) — it is gated on
  paired_utility, predeclared NOW; win-rate and the new margin/bracket
  fields are diagnostic-only. A whole-game or level-laddered leg is
  required before adoption (the 120-cliff and truncation-at-A behavior is
  invisible to one-round metrics; A3/A4).

Stage 3 (new, mandatory — A4/A3 fatal composition attack): the composed
adopted stack is dueled vs the live champion under evaluation.py at a
predeclared paired_utility bar before any composed deploy. Any L-C adoption
re-derives eps and telemetry thresholds and re-validates previously adopted
arms under the new objective (raw-unit thresholds go stale the day L-C lands).

Hardware note (A4, verified consistent with the ledger): both 16c boxes are
busy; stages 0–1 and the stage-2 witnesses are source/laptop work. Nothing
here perturbs the live runs.

---

## Appendix A — what the attackers killed

1. F9 as written — trump candidates are NOT off the ballot; the wide ballot
   prices them in production on every uncapped lead (V1; A2 closed the cap
   loophole empirically).
2. F6's "apparently never dueled" — recorded tie AI_POLICIES.md:491 + 08-12
   STOP JOBS.md:52 (V4).
3. L-A's four structured candidates — three are production no-ops; the F2
   ballot already contained all four roles (A2, A5, A4).
4. L-B's branch taxonomy — instruments the rollout policy, not the incumbent
   generator; the exemplar's own incumbent branch is outside the taxonomy
   under both wirings (A2, A4, A5).
5. L-D's MARGIN language — dead parameter in the champion's play path; "keep
   MARGIN=5" preserves nothing, "MARGIN=0" changes nothing (A2/A3/A4 on V1's
   F3 revision).
6. L-F's tournament.py target — legacy tool; the gating harness is
   evaluation.py and already has half the patch (V4).
7. The F4 evaluative trick table — 54.4/54.4 parity is an ace/junk mixture
   artifact; win rate tracks led-card height; 18.7-vs-7.0 counts the led 10
   against itself (marginal 8.7 vs 7.2, identical to bare-K) (A1).
8. F12's "4 bare-10 leads, 3 won" — 2/4 (play-level) or 2/3 (round_start);
   both losses conceded 20 (A1).
9. F11's "mostly-lost round" — the round was won; seat 2 was the defending
   banker with a locked hand (A2).
10. F2 as harm evidence — 30-world "preference" below noise-expected max-gap;
    300-world fold measured indifference; harm shape 26/2,257 (A1, V3).
11. Q7 as an L-A blocker — candidate cost is +0.82% fleet-wide worst case;
    the +7% precedent predates the report fold (A5).
12. The >=55%/n=120 bars for arms (ii)/(iii) as staged — best-case effects
    are 1–2 orders below detectability at that n (A1, A4).
13. Q3's "no for v1" on a disagreement trigger — the branch-only signal
    misses all 441 follow-restores and certifies confident-branch blunders
    the machinery already flags (A2).

## Appendix B — unresolved

1. **F5, the round-level question (the binding one).** No round-level
   counterfactual has been measured in either direction. The verified harm
   class is 26 instances — too few for corpus inference; prod accrual is
   ~1.2/day. The open paths are offline self-play counterfactual replay of
   the 26-case shape, or accepting mechanism-only status. Nothing in this
   review establishes that the gate's tie behavior costs (or does not cost)
   rounds. (assessment)
2. **Level-blindness of the bracket objective.** The defender-at-K scenario
   where bracket scoring is strictly worse is constructed and numerically
   verified against _score, but no measurement of its field frequency
   exists; phantom cliffs concentrate in high-level rounds — exactly the
   rounds that decide the re-scoped whole-game goal. Half-fix (trump_rank
   for the defending side) is available unplumbed; attacker-side level needs
   API change. Untested either way. (assessment)
3. **Report-stage mean rule as a play rule.** `mc-s0-report-mean` is
   registered but was never dueled as a play rule (the S0 choice raced
   adaptive vs report-lcb only). Open lane, not settled.
4. **Rollout-bias magnitude in the near-tie region.** 68/106 mean-rule flips
   sit inside 1 report-SE, settled by HeuristicBot's systematic quirks;
   direction documented (mcbot.py:218-221), magnitude unmeasured.
5. **The bury lane.** F11's first error (keeping doomed H10 over banking it)
   is outside every layer of this design; KITTY_POINT_POLICY's locked-hand
   trigger subpopulation is untested (the global 50% n=200 tie is
   uninformative about a rare trigger). Candidate for its own telemetry
   counter and, later, its own arm. (assessment)
6. **Human-baseline validity in F4.** Effectively 2–4 people; 74% of human
   plays from two names; "james bot" (bot=false) attribution unresolved. Any
   future bot-vs-human table needs clustered SEs or the honest label
   "vs Jerry+Sk".
7. **Partial cap evictions.** 0 of 19 capped ballots lost ALL trump
   candidates, but partial evictions are not measurable from the records.
8. **The exemplar's best play.** Whether the BJ-drain-then-dump-H10 line
   beats both H10 and S3 was never comparable at precision under the current
   topology and cannot be resolved from this corpus. (assessment)
9. **TRUMP_BALLOT's marginal flag.** Near-no-op under WIDE_LEAD_BALLOT but
   not proven a no-op in pair-rich capped hands; unmeasured.

---

## Post-synthesis corrections (completeness critic, applied 2026-08-23)

A final critic pass recomputed the load-bearing numbers and found eight gaps.
None overturns a verdict; all are incorporated below and supersede the
corresponding text above.

1. **Scope of the bottom line.** "The harm case collapsed to a bounded
   1.2%-of-decisions shape" bounds only the F2/F8 *gate-restore* shape inside
   the 2,257 decision records. Reconciliation (recomputed): only **60** bare
   point-single lead decisions carry records at all — 44 gate-restored, 8
   search-endorsed (raw==played==0), 8 gate-accepted challengers — so a
   material fraction of F4's observed point leads never entered any searched
   decision and sit outside both the 26-case bound and ARM ZERO's reach.
2. **F4 row understatement.** V2's corrections shrink the raw feeding gap
   5.3pp → **3.0pp** (43% of the headline), and every F4 rate includes tricks
   from the 21 truncated rounds. V2's play-level figures: bare-10 59/54.2%,
   non-point 1268/54.7%, conceded 20.8 vs 20.1, feeding 40.2% vs 37.2% raw,
   20.7% vs 19.5% controlled.
3. **L-D rebuttal figure.** The "56% of raw 30-world lead disagreements were
   wrong-or-unproven at 300 worlds" has no reconstructable denominator.
   Verifiable figures: wrong-or-unproven-as-restores **262/404 = 64.9%** of
   lead disagreements; outright-wrong (gap<=0) **156/262 = 59.5%** of lead
   restores.
4. **ARM ZERO's k.** The verified 26-case class is defined by gap < 1.70*se
   (mcbot.py:481), so "fixes the entire class" requires **k >= 1.70**; any
   smaller tie window excludes members. The 10/17/79 flip table compares
   candidate point totals at the restore site.
5. **F10 calibration claim.** "E[attacker pts | H10] ~= 67.7 vs actual 65" is
   one realized outcome against a mean — consistent on this single exemplar,
   uninformative about calibration.
6. **F11 bury rule status.** The KITTY_POINT_POLICY locked-hand rule
   (smart.py:43-46) that would have met its own trigger **defaults False —
   dormant**. The bury lane is an adoption question, not an active-rule bug.
7. **F3 dead paths.** Only two conservative reasons ever occur in all 2,257
   records (`report_lcb_below_min_gain` and the report-accept path);
   `selection_underfilled` and `no_report_challenger` never fire in
   production, so most enumerated conservative paths need no respecification.
8. **F5 basis.** "All four verifiers left it untouched" means no verifier was
   assigned it; the verdict stands as a negative claim no checker
   contradicted, independently supported by A2's replay.
