# Active Claude/Codex handoff

> Current operational truth and review queue only. Historical reviews belong
> in `HANDOFF_REVIEW.md` and Git history. A request not listed here is not
> active.

Last reconciled: 2026-08-21 12:45 EDT.

## Immediate objective

Carry the reviewed BELIEF-V1 V2/R4 offline run through its terminal result and
determine whether the learned belief model produces a measurable held-out
calibration improvement over REF-C. Do not convert offline evidence into a
sampler, gameplay, strength, promotion or deployment claim.

## Review queue — empty

Claude's exact-freeze PASS is complete at canonical ledger commit
`0bcb2f821a909bf375caf88ae52a33582b176ebd`. No further source, freeze or
execution review is requested while R4 is running. The next Claude ask begins
only after the supervisor terminalizes or fails and Codex publishes one exact
terminal/reproducibility packet.

Do not re-review PR #122, regenerate the freeze, append another execution
marker, initialize another namespace, or retry this admission.

## Live BELIEF R4 execution

| field | current binding |
|---|---|
| host | `shengji-cloud` (`ubuntu-32gb-hel1-1`, 16 logical CPUs) |
| service | `belief-v2-r4-b78f802-r3.service` |
| source | PR #122 exact head `b78f802b81f86b7c88d529ad62f180eeef558665` |
| source PASS | `db8812304e1095da6887daf5d603f9b80fb7e3e8` |
| freeze | `/opt/belief-r4-freeze-b78f802-r3.json`, SHA-256 `9986d591af844f6e40516c97968fa37a1f08962f57b78992b05ce0775748deb7` |
| execution PASS | `0bcb2f821a909bf375caf88ae52a33582b176ebd`; exact marker SHA-256 `66c72b7084feca2e0f384f0fbb9aca375e12aab9285c409eddc57220eb9f90df` |
| admission | `efdb42a60b1ac579bde8e5a3794af941a0cb3c24208c703cbfde5749eb4231c6` |
| evidence root | `/opt/belief-r4-evidence-b78f802-r3` |
| operations root | `/opt/belief-r4-ops-b78f802-r3` |
| progress source | `/opt/belief-r4-ops-b78f802-r3/status.json` |

The service launched at 12:44 EDT. Initial health verification found all 16
synthetic-capture workers alive, each near one full CPU core, no import/runtime
errors, and the task-weighted counter advancing from 0 to 0.02%. The immutable
plan contains 85 tasks across ten ordered stages. Read `status.json` for the
current percentage; this launch snapshot is not a substitute for the live
counter.

The first initialization command refused before creating any namespace because
the detached checkout's `origin/main` ref was stale. Codex refreshed only that
remote-tracking ref, confirmed the evidence root/tombstone were still absent,
then initialized successfully. This was not a consumed execution or retry.

## Safe monitoring and authority

- Safe to inspect: systemd state, process identity and resource use,
  `status.json`, and worker stderr for failures/progress records.
- Do not manually open calibration/test outcomes, model-selection results or
  terminal scientific bytes while the supervisor owns the pipeline.
- The supervisor is sequential and fail-fast. A nonzero worker exit stops the
  DAG; retry is false.
- The one true grant is bounded capture, reference, training, calibration and
  one terminal test opening. Sampler implementation, gameplay screen, strength
  claim, promotion, deployment and retry remain false.
- The training wall cap is 48 hours. The frozen next-epoch estimate is about
  5.51 hours; graceful deadline truncation seals the best common completed
  epoch instead of discarding a healthy curve.
- R1 is spent and immutable. R2 was blocked and never initialized. Neither may
  be reused as an R4 input.
- Do not stop, reboot or power off `shengji-cloud` while the service is active.

## Next gate

1. Codex monitors the live outcome-blind counter and reports stage/percentage.
2. The supervisor either completes all 85 tasks or publishes one fail-closed
   terminal failure; no operator retry is permitted.
3. Codex verifies and packages the exact terminal artifacts without making a
   strength claim.
4. Claude performs one consolidated terminal/reproducibility review.
5. Only that reviewed terminal result answers whether BELIEF learned a
   measurable held-out advantage and whether a separately reviewed sampler
   implementation should be designed.

## Standing invariant

Integrity protects the scientific question; it is not the result. A clean run
must still be allowed to report no learning. A positive offline result permits
only the next design/review rung, never direct gameplay or production use.
