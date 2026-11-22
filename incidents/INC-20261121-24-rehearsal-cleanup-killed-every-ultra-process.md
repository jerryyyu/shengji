# INC-24: A rehearsal's cleanup step killed every jeryyu process on the Ultra

**Date**: 2026-11-21

**Severity**: S3. No wrong data entered any training set or measurement, and
no finished result was lost. A live training lane, the armed FT-RT3 waiter and the
Darkbloom provider were killed with SIGKILL. (RT4's waiter had already stopped at
06:26:08Z and was started for the first time during the recovery.) The lanes were restarted about
four minutes later; the cost was a few minutes of cache work and a restart of
the cache step.

**Status**: closed for the lanes; the GPU swap rehearsal stays stopped until a
cleanup that kills only its own children is reviewed.

## What happened

At about 22:20:30Z on 2026-11-21, a Claude subagent rehearsed the GPU driver
swap for FT-RT3 and RT4 (the second HOLD on #1648's lane amendment). Its
harness started inert fake drivers under `claude-gpu-work/rehearse-swap/<case>/`
and, between cases, cleaned them up with:

```
P="/bin/bash $C/" ps … | awk 'index($0, ENVIRON["P"])' | … kill -KILL
```

The `P=` prefix sets the variable for `ps`, not for `awk`. `awk` saw an empty
`P`, `index($0, "")` matched every line, and the loop sent `kill -KILL` to every
process owned by `jeryyu`. The swap script under test was not involved; its
happy case had just passed.

Killed:
- the ft500 driver (pid 1800), its `train.sh` (49838) and the cache workers
  it had just started;
- the FT-RT3 CPU waiter (15153). RT4's waiter (15246) was not running: its `DRV.status`
  shows STOPPED at 06:26:08Z, about 16 h earlier;
- the Darkbloom provider. Its watchdog relaunched it.
- the subagent's own ssh session.

SIGKILL skips traps, so the lanes wrote no STOPPED lines. The host lock (owner
`claude ft500 FT pid=49838`) and the UT-GEN2 HOLD (owner `pid=1800`) were left
behind.

## Impact

- **ft500:** the joint pass reached 1042/1042 and wrote `FT TRAINED` at
  22:20:29Z, about a second before the kill. `cand/train/best.pt` survived
  (sha256 `fbf1315e…`). The cache step had just started; its shards are
  written via a temp file and `os.replace`, so the 21 on disk were whole and
  the restart keeps them.
- **FT-RT3 and RT4:** the FT-RT3 waiter was killed; RT4's had been stopped since
  06:26Z. Because no waiter was alive, neither lane could start on an unfinished ft500. The FT-RT3 waiter treats "predecessor
  pid gone" as an end condition, so if it had survived it would have started
  on an ft500 with no package. RT4's waiter had not been running since
  06:26Z.
- **Darkbloom:** the watchdog restarted on launchd's schedule, and its own
  auto-restart relaunches the provider.

## Recovery (22:24Z)

1. Confirmed that pids 49838, 1800, 1817 and 15153 were dead (and 15246 was already gone).
2. Cleared the stale lock and HOLD only after checking that each one's owner
   line named a dead pid. Copies of both are in `claude-gpu-work/incident-stale-*`.
   Logged in `claude-ft500/INCIDENT.log`.
3. Relaunched the unchanged ft500 `driver.sh`, detached (pid 85647,
   `self=03c46d89…`, the same sha as the 05:53Z START). It passed CUT and COUNT
   and resumes at the cache step, keeping the shards already written.
4. Re-armed the unchanged FT-RT3 waiter, and armed RT4's for the first time since 06:26Z, (`driver.sh`, `self=328c390a…`, pid
   86074, `FXPID=85647`) and the RT4 waiter (`driver.r2.sh`, `self=8baa31bc…`,
   pid 86141, `FRPID=86074`). These are the same launchers as the 06:25Z
   STARTs.

## Why

- The cleanup built its kill list from a pattern match over `ps`. A pattern
  that silently becomes empty matches everything.
- Nothing refused a kill-by-pattern:
  - the capsule's FORBIDDEN list said "no stopping, starting or signalling any
    real process", but that is prose the harness could not check;
  - the Claude guard hook covered `rm`, `git` and test pipes, but not `kill`.
- This is the same class as INC-12 and INC-16 (process filters that matched
  the wrong processes) and the repeated "ps-grep gate matches its own command
  line" near-misses. A repeated rule moves up to an enforcer.

## Rule and enforcer

A process is signalled only by a literal pid whose command line was checked.
A script kills only the children it started, by the `$!` it saved. It never
kills from a `ps`, `pgrep` or `awk` match.

- **Enforcer (Claude, partial):** the PreToolUse guard hook (Claude's user
  settings, outside the repo) now refuses `pkill`, `killall`, and any `kill`
  whose targets are not strictly positive literal pids. That covers variables, loops,
  `xargs` and command substitution, including inside ssh remote commands. It parses one
  leading signal selector (`-9`, `-TERM`, `-s TERM`, `-n 9`) and an optional `--`, then requires
  every remaining operand to be a strictly positive literal pid. A `0` or negative operand anywhere
  (process-group semantics) is refused, as in `kill 123 -456`; `kill -0` probes are allowed.
- **Limit:** the hook sees only commands typed into the Bash tool. A script
  file run by the tool, which is how this harness ran, is not inspected.
  Rehearsal harnesses therefore record the pids they spawn and kill only those.
  The staged replacement harness is not to run until it has been reviewed.
