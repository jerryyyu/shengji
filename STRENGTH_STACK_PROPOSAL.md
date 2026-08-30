# Strength stack proposal — lead quality, gating, objective, harness

> **Proposal, 2026-08-23. Selects nothing.** No gameplay code changes here; no
> strength claim; nothing clears any adoption bar. This is the focused design
> requested in the PR #127 review ("HOLD any gameplay change until that
> focused design is reviewed"). Every claim below survived an 11-agent
> adversarial review (4 independent verifiers, 5 attack lenses, synthesis,
> completeness critic) recorded at
> `docs_archive/gameplay-stack-adversarial-review-2026-08-23.md` — several of
> the motivating findings did **not** survive and are listed as killed.
> Champion under discussion: `mc-s0-report-lcb` at origin/main.

## 1. What motivates this, honestly

A player reported bots feeding points, leading points, and bare-10 leads. The
adversarial review left the *statistical* harm case weak and the *mechanism*
case strong:

- **Statistics (weak).** The feeding complaint does not survive controls
  (3.0pp raw gap after seat-attribution correction; 1.2pp controlled). The
  famous 54.4%-vs-54.4% "bare-10 wins like junk" parity is an aggregation
  artifact (ace singles win ~83%, junk ~50%; "non-point" mixes both). The
  exemplar hand (TZGK r6 H10) was played by the **defending banker with a
  locked 15-trump hand, whose team won the round** — the trick lost 20 points
  and the round was won anyway; the first genuine error in that round was at
  the **bury**, not the lead. No round-level harm was ever measured (F5).
- **Mechanisms (strong, all source-verified).**
  1. `MARGIN=5` is **dead code** in the champion — the report block returns
     first on every searched decision (mcbot.py:470-530; registry
     REPORT_RULE="lcb"). The gate that actually decides is the report-LCB.
  2. The report gate restores incumbents on statistical ties with **no
     point-risk tie-break** — POINT_SHY runs earlier, inside `_pick_index`,
     and the gate can undo it (verified call order). 26 of 2,257 recorded
     decisions (~1.2%) are gate-restores where the incumbent risked more
     points than an equal-scoring challenger.
  3. There is **no prior-confidence signal**: a last-resort fallback lead is
     defended by the same gate as a measured-56% tractor lead. (Only two
     conservative reasons ever fire in production, so the fix surface is
     small.)
  4. The heuristic's `avoid_points` is a sort key, not a filter
     (heuristic.py:338-339): the fallback branch can lead a bare point card.
  5. The rollout objective is raw `float(clone.attacker_points)`; the
     written bracket objective (mcbot.py:928-941) is off, and its one
     recorded outing was a **tie** (AI_POLICIES.md:491) stopped on 08-12.
  6. The gating harness (`evaluation.py`) records binary outcomes only —
     point margins and bracket outcomes are discarded, wasting sensitivity.

So the honest framing: this is a **decision-quality and evidence-sensitivity
program**, not a repair of measured harm. The one player-facing fact that
survives is salience (F12): a partner-bot's bad-looking lead costs trust even
when round-EV-neutral.

## 2. The power problem — decision required before any duel

The standing bars (>=55% round-level, n>=120) **cannot detect any arm's
plausible effect**. ARM 0's best-case direct effect is ~0.6pp of rounds
(~26/2,257 decisions, partially compensated downstream); detecting 0.6pp at
80% power needs on the order of **54,000 rounds**. Three options, one must be
chosen and pre-registered:

- **(a) Non-inferiority + witness adoption** for harm-class fixes: adopt if
  byte-identical off-class (witnessed) and not-worse on a bounded duel — the
  menu-widening precedent ("adopts at neutral") extended to
  provably-off-class-identical policy changes. Cheapest; requires Jerry to
  extend the bar's definition.
- **(b) Sensitivity via margins**: land the harness patch (§3 L-F) first and
  gate on point-margin / bracket composites, which the review estimates
  recovers most of the missing power at n=120–500.
- **(c) Directional screens only**: accept that duels at n=120 are
  screens, never confirmations, and say so in every result.

## 3. The program

### ARM 0 — report-stage point-shy tie-break (run first; ~10 lines)

At the restore site (mcbot.py:494-497): when the 300-world fold measures a
statistical tie (`|gap| <= k*se`, **k = 1.70** — smaller k provably excludes
members of the verified class), play whichever of {incumbent, challenger}
**risks fewer points** (candidate point totals at the restore site). Fixes
the exemplar and the entire verified 26-case gate-restore class with no new
candidates, no confidence signal, no objective change. Corpus flip table:
10 worse / 17 better / 79 equal on point risk among the 106 gap>0 lead
restores.

Carried caveats: (i) "points at risk" ignores trump-length cost — it tilts
toward spending trump singles, so the result must include a stratified
drain/cash/junk report; (ii) ARM 0 reaches only record-backed decisions —
of the observed bare point-single leads, only 60 carry decision records
(44 gate-restored / 8 search-endorsed / 8 gate-accepted); forced and
unsearched point leads are out of scope.

Witnesses (prove-the-check-can-fail): byte-identical to champion off-class on
a decision-record corpus; flips TZGK r6 s2 H10->S3; a deliberately broken
variant turns each witness red.

### ARM I — lead-ballot widening, shrunk (menu bar: neutral)

The original four-candidate proposal died under review: the wide ballot
already prices trump leads (F9 refuted — WIDE_LEAD_BALLOT adopted at 62%
generates trump tractors/pairs/tops), and three of the four proposed
candidates are redundant with it. What remains: **one** non-redundant
candidate (lowest non-point single across all plain suits — the cross-suit
exclusion the heuristic lacks) plus activating the already-written
`V3_LEAD_SINGLES` lane, both under a mandatory dose witness so equal-work
attribution holds.

### ARM II — unsure-lane gating (preference bar; see §2)

Confidence provenance is respecified onto **SmartBot's** lead branches (the
actual incumbent generator — the original design instrumented HeuristicBot,
the rollout policy; the exemplar H10 came from a branch outside the proposed
taxonomy under either wiring), carried as **data in the decision record**,
not control flow, plus a statistical deficit trigger derived from stage-0
telemetry. When unsure: `REPORT_RULE="mean"` (the registered, never-dueled
`mc-s0-report-mean` lane) with ARM 0's tie-break. **Guard:** the unsure lane
keeps the LCB for **all-trump challengers** — 50.0% of gate-restored lead
challengers are all-trump, and cheap-trump drains are a measured -4pt
rejected family (TRUMP_DRAIN_V2, "measured: hurts"); v1 relaxes non-trump
challengers only. One challenger-budget option (successive halving / raised
N_DET on the unsure subset / k-challenger fold) must be chosen and stated
before the duel — the two-candidate fold's challenger-selection noise is a
verified flaw (64.9% of 30-world lead disagreements are wrong-or-unproven at
300 worlds; the gate does real epistemic work and is not simply removed).

### ARM III — bracket objective retest (preference bar; see §2)

`LEVEL_OBJECTIVE=True` as a **changed-stack retest** — its prior recorded tie
predates the report-LCB champion, so the question is open again, but it is a
retest and must say so. Requirements: recalibrate `POINT_SHY_EPS` (2.0 in
40-scaled units is a ~10-raw-point window — silently wider than intended);
gate on **paired level-utility**, not raw points; note the objective remains
level-*blind* (conditions on round points only, not the teams' current
levels) — the review constructed cases where this chooses worse than raw
points, recorded as unresolved.

### Stage 0 (now, no hardware): offline analysis + telemetry spec

~90% of the needed telemetry already exists in production decision records.
Offline first: fallback frequency, gate-restore stratification, deficit
distribution — from the 2,257 records on disk. The small prod telemetry
patch (branch provenance in the record) follows the witness protocol.

### Stage 1 (harness): margins + brackets in `evaluation.py`

Measurement-only. Records point margins and bracket outcomes alongside wins
— retargeted from tournament.py (legacy Elo tool) to the actual gating
harness. Enables option (b) in §2 and sharpens every later duel at fixed n.

### Candidate arm from the review (new): the bury lane

The exemplar round's first genuine error was the **bury**, and the
already-written `KITTY_POINT_POLICY` locked-hand rule (smart.py:43-46) would
have met its own trigger — it **defaults False (dormant)**. Activating it is
an adoption question with the same power caveats; recorded here so it is not
lost.

### Ordering and attribution

ARM 0 -> stage 0/1 -> arms I–III, each with trigger-matched nulls and a
predeclared comparison graph; a **composed-stack confirmation duel** is
mandatory before any combination ships. Arms interact (widening changes what
the objective scores), so single-change attribution is preserved by the
predeclared graph, not by hope.

## 4. What the review killed (do not resurrect without new evidence)

- Four-candidate unsure ballot (3 of 4 redundant with the wide ballot).
- "Rollout opponents are too passive" (both punishment mechanisms verified
  present; the exemplar replays correctly).
- MARGIN-based gating language (dead code in the champion).
- The 54.4/54.4 parity statistic (aggregation artifact) and the raw feeding
  gap as harm evidence (attribution artifact).
- "LEVEL_OBJECTIVE was never tested" (recorded tie + 08-12 STOP).
- HeuristicBot as the confidence-signal host (wrong generator).

## 5. Unresolved, carried honestly

- **F5**: no round-level counterfactual for point-leads exists in either
  direction; stage 1 margins make it measurable.
- Bracket objective level-blindness (worse-than-raw constructions exist).
- Whether option (a)'s witness-adoption extension is acceptable — Jerry's
  call, since it modifies the meaning of the adoption bar.
- Hardware: both 16c boxes are committed to BELIEF R4/R5 for days; nothing
  above stage 1 can run until one frees. Stage 0 needs no box.
