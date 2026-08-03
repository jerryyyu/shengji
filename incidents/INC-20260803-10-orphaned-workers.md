# INC-10: Orphaned workers wrote buggy-code data into the live dataset

**Date**: 2026-08-03 (onset 2026-08-02 ~23:52, found ~09:20)
**Severity**: S1 — data-corrupting
**Status**: fixed; 4 shards quarantined; guard shipped

## What happened
Two generation workers survived a kill, kept running **10 hours** on a
version of the engine with a known cache bug, and silently wrote two
fresh shards into the dataset that v8 was going to train on. A second
instance of the same bug on the Air left 7 workers running 2 extra hours
alongside their replacements (no data written — buffers hadn't flushed).

## Timeline
- 23:52 — 2 gen workers launched (offset 110) on code containing the
  cache-key bug later found by the audit (see INC-07).
- 00:45 — bug fixed in the repo. Running workers keep the old code:
  **Python loads code at process start**.
- ~02:00 — I quarantine the two shards those workers had written and
  "kill" them with `pkill -f "gen_v3_mini 4000 2 30 110"`, then relaunch
  replacements. I do not verify the kill.
- 02:00–09:20 — the workers are still alive. They flush 2 more shards
  (`shard_110001`, `shard_111001`) into the live dataset. Every fleet
  check reads "N hot workers / X% CPU" and looks healthy.
- 09:20 — a process-age audit (added that morning after unrelated
  curiosity about long-running jobs) shows two processes aged 10h24m.
  `lsof` identifies them as writing `gen_v3_mini2.log`.
- 09:25 — killed by PID; both shards quarantined; ledgered.

## Impact
2 shards / 100k decisions of suspect data reached the live dataset and
would have entered v8's training set. ~20 core-hours burned on work that
was deleted. On the Air, ~14 core-hours burned and its replacement run
was throttled to half speed by the zombies for 2 hours (which I had
misdiagnosed as "the Air is just slow when niced").

## Root cause
`pkill -f <pattern>` matched the multiprocessing **pool parent** (which
carries the full command line). Spawned workers appear as bare
`python3 -c from multiprocessing.spawn import spawn_main ...` and did not
match, so they were never signalled. The parent's death does not
propagate to spawned children.

## Why detection took 10 hours
1. **The kill was never verified.** No error from `pkill` was read as
   success.
2. **Every monitor measured aggregates, not identity.** "12 hot / 933%"
   is a health metric; orphans hide inside it looking exactly like real
   work. The question I was answering was "is the machine busy?" when it
   should have been "is the machine busy doing what I think?"
3. **Shard counting was aggregate too.** A rising total reads as
   progress. Grouping shards by worker id — done for the first time that
   morning — makes an impossible id obvious instantly.
4. **No test can see this.** The 60-test suite validates the engine;
   this was an operational property (a stale process writing files).
5. **Luck of buffering**: with 50k-decision buffers the orphans produced
   no artifacts for their first ~8 hours. The smaller shard size adopted
   later that night for durability would have surfaced them sooner.

## Fix
- Killed by PID; quarantined `shard_110001`, `shard_111001` (joining the
  2 earlier shards from the same workers) in `rl_data/gen_v3_quarantine/`,
  excluded from all training.
- Kill procedure changed to: `pkill` the parent, then **enumerate
  survivors by open files and kill by PID**, then verify none remain.

## Prevention (shipped)
- `scripts/fleet_status.sh` gained an **integrity section**: identifies
  every long-running Python process by its open files (flagging anything
  unidentified or unexpectedly old) and lists the worker ids currently
  writing shards, so an id with no live owner is visibly an orphan.
- `CORRECTNESS.md` rule: *"pkill by parent cmdline does NOT kill
  multiprocessing workers; always follow with a process-age audit."*
- Shard size reduced 50k → 10k decisions, shrinking both the crash-loss
  window and the time-to-visibility of a rogue writer.

## Lesson
**Aggregates hide identity.** Any monitor that answers "how much is
running" without answering "what exactly is running" will let a
misbehaving process masquerade as healthy load for as long as its
artifacts stay buffered.
