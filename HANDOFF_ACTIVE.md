# Active Claude/Codex handoff

> **Canonical paths:** coordinate only through `HANDOFF_ACTIVE.md` and
> `HANDOFF_REVIEW.md` on canonical `main`. Branch-local copies are not review
> authority. Raw review markers belong only in the append-only review ledger.

Last reconciled: 2026-08-15 after fresh Mini B2 design freeze.

## Immediate objective

Review the frozen Mini-specific BELIEF-V1 B2 design, then use one consolidated
execution to answer the offline question: does a history-aware, actor-visible
ownership model improve held-out hidden-card calibration over the corrected
current constraint sampler? The source gate is complete. This is an
infrastructure/calibration milestone, not a strength or deployment claim.

In parallel, implement the reviewed three-arm ballot-widening confirmation
design as the next whole-game causal experiment. Defer the Pair checkpoint V2
diagnostic implementation unless the user explicitly reprioritizes it.

## Review queue — precise asks

1. **BELIEF Mini V2 design — current blocker.** Review immutable design
   `/Users/jerryyu/Projects/belief-v1-b2-mini-v2/design.json`, SHA-256
   `a8c5e05f490e1bb628958a3a9a047870979513751353fc7a8e7be2f8a1c1fd53`.
   It binds merged source `959c05d`, protocol `fa485d51…02dc4`, 105-file
   source manifest `818912dd…04000`, Mini boot `4da8ae43…03344`, Python 3.14.3,
   Torch 2.13.0, NumPy 2.5.1 and native binary `4772973c…dff20`. Require mode
   `0400`, one link, canonical/live reopen, clean checkout, one native binary,
   no bytecode, and absent evidence/partial/tombstone/log paths. Review the
   exact `BELIEF_V1_B2_RUNBOOK.md` stage order, caps and false authority map.
   Introduce exactly one `BELIEF_V1_B2_OFFLINE_EXECUTION_V1_REVIEW` marker on
   canonical main. PASS authorizes only this exact consolidated offline run;
   it cannot authorize B3, gameplay, strength or deployment.

2. **Repository hygiene follows compute admission.** PR #115 and compacted
   docs PR #114 are green/mergeable but are not the current compute blocker.

## BELIEF-V1 current truth

| layer | state | what it proves / does not prove |
|---|---|---|
| **B0 contracts** | Merged. Actor-visible observation bytes and privileged hidden targets are typed, separated, hash-bound and adversarially tested. Ownership marginals enforce conservation, void/pair-cap facts, and sound banker-hand-or-kitty declaration eligibility. | Proves the information boundary and mechanics substrate. It does not prove learning or strength. |
| **B2 offline pipeline source** | PR #113 exact `3ee0eb8` externally PASSed and merged byte-preservingly through main `959c05d`; 187 BELIEF tests passed in pure and strict compiled modes. | Implements deterministic capture, corrected REF-C scoring, 8+8 cohorts, controls, calibration/mechanics evidence, sealed one-shot test opening and independent reopen. Source readiness is complete. |
| **B2 design/data/result** | Fresh Mini design `a8c5e05f…1fd53` is frozen and independently reopens, but has no external marker yet. Evidence root, partial, tombstone, supervisor log, corpus, reference worlds, checkpoints and terminal result are all absent. | Source/runtime/population/caps are concrete. No execution has started and no calibration lift has been measured. |
| **B3 sampler** | Not implemented or authorized. | No learned posterior is feeding Monte Carlo worlds. |
| **B4/B5 decision and strength gates** | Not started. | No policy, gameplay, strength, promotion or deployment claim exists. |

The earlier Mini design belongs to a rejected source head and must never
initialize. The fresh V2 design requires one exact marker review before the
consolidated run.

## Compute and fleet

| host | current state | next use |
|---|---|---|
| **Mini** | Idle; fresh design `a8c5e05f…1fd53` frozen, no BELIEF execution started. | After exact design-marker PASS, run the consolidated B2 pipeline once. |
| **Air** | Idle after the broad Pair fixed timeout. | No retry/resume/partial use. Keep free unless a new reviewed job is selected. |
| **Strength Cloud** | Powered off. | Keep off; S4 terminally selected none. |
| **Performance Cloud** | Powered off. | Keep off; the Pair checkpoint V1 attempt was spent and produced no terminal evidence. |
| **Production** | `mc-s0-report-lcb`, release 18. | Unchanged by BELIEF-V1; no deployment authority. |

The frozen planning caps for the eventual Mini B2 run are 4,096 champion
rounds split 3,279 train / 407 calibration / 410 test; 16 capture lanes; 256
REF-C worlds per held-out decision; eight candidate and eight permuted-label
members. Planning caps are 16 capture core-hours / 2 wall-hours, 64 reference
core-hours / 8 wall-hours, and 32 device-hours / 8 wall-hours. Fresh host
preflight and the V2 design remain authoritative; these are ceilings, not a
promise that every stage consumes the full amount.

One reviewed marker should cover the complete sequence: initialize, capture,
reference generation, both cohorts, the single test-decision opening, terminal
verification. Do not insert per-stage review handshakes unless a named guard
fails. Any failure consumes only the authority defined by the frozen design;
there is no retry by default.

`BELIEF_V1_B2_RUNBOOK.md` freezes the detached stage order, fail-stop behavior,
sealed-log boundary, monitoring allowlist, and terminal routing. It is an
operational procedure only and adds no review or execution authority.

## Closed fleet results that determine the plan

- **T4:** terminal `SELECT_NONE` for the learned treatment. Its uninformed
  widening arm beat champion, but used +14.8% accepted worlds and +80.9%
  searches, so widening and compute are confounded.
- **S4:** completed both looks and terminally `SELECT_NONE`.
- **S6 (shuai-pai sourcing):** recovery aggregate terminally
  `SELECT_NONE_FOR_FRESH_SCREEN_DESIGN`; bury-side criteria passed but the
  combined lead source failed three gates.
- **Broad Pair:** fixed 64.08-hour timeout with 0/8 terminal shards and no
  evidence; no retry or partial interpretation.
- **Pair checkpoint V1:** one-shot attempt spent on treatment-work telemetry
  drift; no terminal evidence. Claude's checkpoint diagnostic is a reviewed
  design input only.

## Next experiment design inputs

Claude recorded two design inputs on canonical main at `bf4386b`:

1. **Three-arm ballot widening — implement next.** Arms are literal champion,
   widening at champion work, and widening at the original T4-null work. This
   separates action-set value from added compute. Implementation/design/tests
   only; no packet freeze or launch until its own exact review chain.
2. **Pair checkpoint V2 diagnostic — defer.** It would recompute microshard 3
   score-free telemetry to identify exact-work, no-op-dose, mode-off, or
   platform dependence. It is useful diagnosis but lower priority after two
   Pair attempts produced no whole-game evidence.

## Authority boundaries

- A design PASS authorizes only the next named implementation or freeze step.
- A source PASS does not authorize compute.
- BELIEF B2 may open its test split exactly once only under the fresh reviewed
  V2 design marker; verification may re-read bytes but cannot create a second
  decision.
- B2 cannot launch gameplay and cannot claim strength. A positive B2 result
  opens B3 sampler design/review only.
- Never inspect, resume or aggregate spent T4/S4/S6/Pair namespaces outside
  their existing terminal verifiers.
- Never deploy, restart production, wipe rooms, power on paid cloud compute or
  launch a scored job without the task's explicit authority.
