# INC-16: S4's handoff queue would have mistaken tmux for a live capture worker

**Date**: 2026-08-12, 17:45–18:38 EDT

**Severity**: S4 — operational near-miss caught before impact

**Status**: contained; waiting queue replaced; capture and S4 evidence untouched

## What happened

Cloud's 16-core Pair V3 capture had to finish before the reviewed S4
confirmation could start. A detached handoff queue correctly waited for the
capture supervisor and checked the exact capture outputs, S4 worktree, packet,
source and review hashes before admission.

Its post-capture absence check was too broad:

```text
pgrep -f 'pair_ballot_affected_states.py capture.*--seed0 ...'
```

The tmux server that owns both detached sessions retained the command line of
the first session that created it—the Pair capture launcher. That process is
not a Python worker and performs no capture work, but its argv still matches
the substring. Because the same tmux server must remain alive to host the S4
queue, the original queue would have exited `HOLD` immediately after the real
capture supervisor and workers finished.

The defect was found during a bounded pre-launch audit while all 16 real
capture workers were still healthy. The broad probe saw 18 matching process
records during the audit, whereas an executable-identity probe found exactly
the 16 Python capture workers.

## Impact

- No capture worker was stopped, duplicated or slowed.
- No S4 admission, receipt, worker, gameplay or outcome existed.
- No scored or score-free evidence byte was opened or changed.
- No Cloud compute was lost. Without the audit, Cloud would have gone idle at
  the Pair-to-S4 transition until the false `HOLD` was diagnosed.

## Root cause

The queue treated a command-line substring as process identity. Long-lived
wrappers such as tmux, shells and supervisors can retain child-command text in
their argv after the child cohort is gone. A positive `pgrep -f` match therefore
does not prove that a worker executable is alive, just as INC-12 established
that a negative substring match does not prove that a job is dead.

## Containment

1. Staged and syntax-checked queue v2 before touching the active queue.
2. Replaced only detached zero-CPU session
   `s4-c2-360b-launch-queue`; the Pair capture session was not signalled.
3. Queue v2 resolves `/proc/<pid>/exe` and counts only the pinned Python
   executable whose NUL-delimited argv carries the exact producer, seed and
   deal limit.
4. Verified the new predicate reports exactly 16 live workers while the broad
   predicate over-counts, then verified queue v2 is detached and the S4
   namespace still contains only its reviewed design snapshot and packet.

Queue v2 hashes to `4d6471803ee5a65a1b7ce21130f8f79f67db358f92dcc3bdcd9003b912f49321`.
It retains every original completion, cleanliness, source, packet and authority
guard.

## Prevention

1. **A PID match is not an identity.** For launch/stop decisions, bind the
   executable plus immutable run arguments or an owned PID receipt; never rely
   on `pgrep -f` alone.
2. **Test both sides of a process predicate.** While workers are live, the
   exact predicate must count the expected cohort despite wrappers. After the
   supervisor exits, it must count zero while tmux remains alive.
3. **Audit transition guards before the transition.** A sleeping queue is code
   on the critical path even though it uses no CPU. Exercise its read-only
   identity predicates while there is still time to replace it safely.
4. **Keep absence checks layered.** Supervisor exit, exact executable identity,
   terminal score-free progress, complete output count and zero partials must
   agree before a successor consumes a host.

## Lesson

**Substring process searches fail in both directions.** INC-12 was a false
negative; this was a false positive. Fleet authority requires executable,
namespace and progress identity together.
