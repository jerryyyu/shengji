# INC-19: BELIEF R4 made verification the critical path and discarded useful work

**Date**: 2026-08-30

**Severity**: S3 — repeated multi-day compute and delayed scientific learning;
no corrupted result or strength claim

**Status**: operational repairs in progress; R4 scientific conclusion still
pending

## What happened

BELIEF R4 was designed as an all-or-nothing evidence pipeline. Training was the
visible expensive stage, but capture, cache construction, calibration, test
scoring, immediate reconstruction and a second verifier also sat on the
critical path. Several of those downstream stages repeated the same expensive
reads and scoring through the same implementation, often with little
parallelism.

The original deadline contract also refused to seal at expiry. A conservative
epoch estimate was used both to admit work and to size the fixed wall, so a
healthy cohort that was still improving could reach the clock and lose its
usable boundary. Completed capture, reference and checkpoint artifacts were
treated as attempt-local even when a downstream defect was orthogonal to them.

Rehearsals exercised helpers and small populations but did not execute every
production terminal wire at representative scale. Several defects therefore
appeared only after hours or days: helper checks were correct while the terminal
aggregation was not, progress accounting did not cover opaque serial work, and
resource behavior differed at full artifact size.

## Impact

- Multiple attempts consumed substantial compute before producing an
  interpretable calibration result.
- Valid completed artifacts needed special recovery work instead of being
  reusable by construction.
- Integrity and reconstruction work became longer than the scientific scoring
  it was intended to protect.
- The user could not reliably answer “what remains and when will it finish”
  from stage progress alone.
- R4 has not yet established whether BELIEF improves prediction; this incident
  is operational evidence only.

## Root causes

1. Reviews optimized individual guards and stages rather than the full DAG and
   its wall-clock critical path.
2. Artifact integrity, scientific validity and independent reproduction were
   bundled into one terminal success bit.
3. Deadline expiry meant loss instead of sealing the best completed boundary
   as explicitly truncated.
4. Recovery and reuse were retrofitted after failure rather than designed and
   rehearsed before the one-shot opening.
5. Several witnesses tested helpers below the altitude where terminal records
   were assembled.
6. CPU scaling and exact full-size terminal performance were not measured early
   enough on the intended host.
7. Review rounds accumulated around narrow mutations without always directly
   unblocking the next executable action.

## Durable prevention

The enforceable workflow rules now live in `AGENTS.md`:

1. Review the complete DAG through scoring, reconstruction and verification;
   publish critical-path ETA, fan-out and duplicate-work analysis before launch.
2. Benchmark the exact heavy path on the intended host and use measured safe
   parallelism before scaling.
3. Seal the first interpretable scientific result before optional independent
   verification; track verification status separately.
4. Treat a deadline at a valid completed node as graceful truncation, never as
   automatic destruction of all progress.
5. Make material nodes immutable, resumable and reusable by semantically
   compatible descendants; rerun only the invalid dependency cone.
6. Rehearse the production terminal wiring and its failure outputs, not only
   helper functions or reduced arithmetic.
7. Require each review PASS to unblock a named next action and consolidate the
   dependency cone into one launch-ready packet.
8. Align with the user before adding duplicate multi-hour integrity passes or
   changing a resource cap after observing the projection.

## Closeout condition

After R4 terminalizes, append the measured stage durations, reused versus rerun
artifact inventory, final verification outcome and any remaining prevention
gap. Scientific BELIEF findings belong in `AI_POLICIES.md` and `RL_PLAN.md`, not
in this incident.
