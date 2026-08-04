# Sourcing-miss audit, 2026-08-02 (n=1052), archived 2026-08-04

Superseded by the current numbers in AI_POLICIES. Kept because the per-category
breakdown is what motivated the v2 ballot.

## Sourcing-miss audit (2026-08-02, human corpus n=1052)

15.3% of human plays are ABSENT from the bot's play-time ballot (v1):
lead throws 77% missing (2/4-card throws: 100%), follow singles 21%
(discard selection — biggest absolute bucket, 116/558), broken-structure
follows 12-17%. Direct confirmation that the gap is sourcing, not
ranking. Fixes staged: ballot v2 lead throws (RL, next teacher gen),
WIDE_LEAD_BALLOT (MC, in measurement), wide-follow ballot (queued).
**Same-day fix loop**: v2 enumerator (exhaustive follows + safe/near-boss
throws) cut misses to 2.3%; adding arbitrary 2-3 component throws per
suit (humans throw riskier than near-boss) cut them to **0.7% — 99.3%
coverage**. Tracked tripwire: `scripts/audit_sourcing.py` (--v2).
Direct net duel same day: rl-v6 beat rl-v5 54% (108-92, n=200) — v6
confirmed the stronger net; old cross-pool Elo suggesting otherwise was
pool-relativity.

### Expert-strategy research: scorecard (2026-08-03)

Five of the nine ranked candidates from the Chinese-strategy research pass
have now been measured. **None helped; one hurt.**

| candidate | result |
|---|---|
| #1 ACE_SEQ (cash aces in follow-able suits first) | 50% |
| #3 NO_OPEN_POINT_SUIT | 50% |
| #1+#3 combined | 50% |
| #2 KITTY_POINT_POLICY (numeric bury caps) | 50% |
| #4 TREE_PLANTING 树套 | **45% — harmful** |

Contrast with rules derived from Jerry's OWN play observations, all
adopted: CONTROL_LEADS 67%, LATE_TRUMP_PAIRS 60%, WIDE_LEAD_BALLOT 62%,
WIDE_FOLLOW_BALLOT 60%. **Human strategy-guide wisdom has contributed
nothing measurable to this bot; watching a specific human play it has
contributed most of the heuristic gains.** Plausible reason: guides teach
humans to compensate for what humans lack (memory, calculation), which
the search already has — while a strong player's live reactions point at
what the bot *specifically* gets wrong.

### Sourcing improvement roadmap (ranked by evidence)

"Ballot" = the candidate list a bot actually scores; a play off the
ballot can never be chosen, however good. Sourcing = what gets on it.

| # | surface | status | evidence / gate |
|---|---|---|---|
| 1 | **Lead ballots (MC)** — every pair/tractor/near-boss throw, all suits incl. trump, cap 8→14 | **ADOPTED** (WIDE_LEAD_BALLOT) | **62% vs narrow mc** (n=120), +7% latency; 12% of leads now use wide-only plays (mostly trump pairs / top-trump drains) |
| 2 | **Follow ballots (MC)** — bounded exhaustive distinct-code follows behind the constructed seeds, cap 12 | **ADOPTED — 60% (72-48, n=120)** (WIDE_FOLLOW_BALLOT) | follows are 75% of decisions; 21% of human discard choices (116/558) were off-ballot. Gate: vs current mc, n=120; adopt at neutral |
| 3 | **Bury (kitty) sourcing** — structured enumeration of buries (void-emptying × point-keeping × trump-preserving) priced by rollouts | queued | MC_BURY only ever priced 4 hand-built variants; once/round so ~20 candidates is cheap; the ×2 kitty multiplier rides on it |
| 4 | **Declare sourcing** — enumerate declare/wait (and suit) at deal time, priced by rollout | queued | never measured; a fixed threshold today; once per deal ≈ free |
| 5 | **Rollout-interior sourcing** — simulated players inside rollouts still play the narrow heuristic; wide candidates are priced against narrow opposition | fallback design | full widening cost-prohibitive; the affordable version is Pluribus-style continuation strategies (k biased rollout personalities at leaves) |
| 6 | **Net-side sourcing** — ballot-v2 teacher generation, then v8 students; play-time flip only after retraining | queued (RL_PLAN roadmap #5) | a net can never source what its training ballots lacked (Elo-798 rule: never hot-enable) |

After #2, ballot *shapes* are effectively done (99.3% of human plays
enumerable); the frontier moves from "can the bot see the play" to "does
it price it right" — belief-weighted world sampling and pair-void
constraints (see BACKLOG).
