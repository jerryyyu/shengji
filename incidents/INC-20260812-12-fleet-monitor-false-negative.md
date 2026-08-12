# INC-12: A false idle diagnosis launched a duplicate S6 census

**Date**: 2026-08-12, 06:50–07:08 EDT

**Severity**: S3 — wasted compute / operational near-miss

**Status**: contained; original census remained healthy; duplicate workers stopped

## What happened

Eight score-free S6 champion-census workers were running correctly on Air.
A status probe searched for `s6_full_hand`, while the actual command was
`s6_throw_full_hand_champion_census.py`. The empty filtered result was
incorrectly interpreted as “Air is idle” even though the original logs were
advancing and all workers were already detached with parent PID 1.

Based on that false diagnosis, a second eight-worker census was launched in a
new `v2` namespace. A raw process inventory using the exact script name then
showed 16 workers. Only the eight newly-created PIDs were terminated; the
original workers continued to completion.

The first public status message also incorrectly said the original workers had
stopped at 48/64 deals. That claim was withdrawn as soon as the unfiltered
process inventory contradicted it.

## Timeline

- **06:35:13** — original workers 85447–85454 start in
  `s6-full-hand-champion-census-v1` on Air.
- **~06:50–07:02** — narrow process probes use the wrong substring. One probe
  also relies on `rg`, which is not installed on Air. An empty/error result is
  misread as a stopped job.
- **07:06:05** — duplicate workers 86687–86694 start in the separate
  `s6-full-hand-champion-census-v2` namespace.
- **~07:07** — exact process inventory reveals both cohorts. The first bulk
  `kill` syntax is rejected by remote zsh; verification shows every duplicate
  still alive.
- **~07:08** — each of the eight known duplicate PIDs is terminated
  individually and verified absent. Original workers remain healthy and their
  logs advance from 48/64 to 56/64 and terminal shard records.

## Impact

- There was **no 30-minute idle window** and no lost original work. The earlier
  utilization-loss claim was factually wrong.
- Eight duplicate processes consumed roughly one to two minutes of Air CPU and
  temporarily shared cores with the valid run. This is a small direct compute
  loss, but the same failure on a multi-day scored job would be material.
- The duplicate launcher itself exited early because `status` is a read-only
  zsh parameter, leaving its children orphaned under PID 1. The explicit PID
  verification caught and stopped them.
- No utility, winner, score, action, hand, or round outcome was retained by
  either census. The duplicate namespace contains only zero-byte shard logs,
  a launcher error, and its PID list; it published no shard JSON or aggregate.
- No production process, sealed T4 artifact, scored population, or scientific
  verdict was changed.

## Root cause

The immediate defect was a hand-written negative filter treated as positive
evidence:

1. the substring omitted `throw`;
2. the remote host lacked one assumed tool (`rg`);
3. “no matching row” was accepted without checking raw Python processes,
   expected PIDs, log modification times, or output existence; and
4. a replacement was launched before proving the old cohort absent.

The ad-hoc replacement command added a second defect by using a zsh-reserved
variable and lacking a tested supervisor contract.

## Containment

- Enumerated both cohorts by full command and output namespace.
- Terminated only PIDs 86687–86694, one PID at a time.
- Verified none of those PIDs survived and that the original v1 workers did.
- Preserved the duplicate namespace for this incident record; it must never be
  aggregated or reused as evidence.

## Prevention

1. **Zero matches means unknown, not idle.** Before declaring a host idle or a
   job dead, reconcile all four: expected PID set, broad raw Python inventory,
   per-worker heartbeat/log mtime, and terminal output count.
2. **Identify by immutable namespace and exact script, not a remembered
   substring.** Status reports must include host, git, run ID, expected worker
   count and exact output paths.
3. **No replacement before absence proof.** A launcher must refuse while any
   process or artifact owns the same experiment identity; if replacing a
   failed diagnostic, use a new namespace only after the original PID set is
   proven absent.
4. **Verify every stop.** Signal explicit PIDs, re-enumerate them, and inspect
   survivors. A rejected kill command is a failure, never best effort.
5. **Use tested launch supervisors.** Avoid inline remote shells for durable
   jobs. Where `tmux` is unavailable, use a checked supervisor that records its
   PID, child PIDs, exit states and heartbeats and refuses shell-specific
   reserved identifiers.
6. **Make monitors tool-portable.** Fleet checks use POSIX tools available on
   each host, print command failures, and never hide SSH/probe errors behind an
   empty result.
7. **Separate identity metadata from evidence content.** Broad inventory may
   inspect process commands, working directories, file names, sizes and mtimes.
   It may tail only exact reviewed score-free heartbeat/progress paths; a
   generic recent-log fallback must never open sealed outcome-bearing bytes.

## Lesson

**Absence of a filtered row is not evidence of absence.** Fleet utilization is
an identity-and-progress claim, not a grep result. The correct response to a
negative probe is a broader read-only reconciliation, never an immediate
duplicate launch.
