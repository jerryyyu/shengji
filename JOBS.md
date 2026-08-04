# Fleet job ledger — mini (this machine)

The Air keeps its own at `~/Projects/shengji-compute/JOBS.md`; that file is
also the inter-agent mailbox (its `## NOTES` section is read by
`fleet_status.sh` every hourly check). Keep this one current: entries are
deleted when the job is done AND its result is ledgered in RL_PLAN.md or
AI_POLICIES.md, not when the process exits.

## RUNNING

### mini / vleaf-settle block 2 — launched 2026-08-03 22:45
- `scripts/vleaf_settle.py 300 7400000` -> `server/runs/logs/vleaf_settle_mini.log`
- SECOND preregistered block of the Air's settling duel, seeds 7.4M+ (disjoint
  from the Air's 7.1M+). Declared BEFORE seeing either result: the two blocks
  run identical code with disjoint seeds, so they may be pooled to n=1200 —
  and the pooled read is the one that counts. Blocks will also be reported
  separately so the pooling can be checked.

### mini / kitty-duel — DONE 2026-08-03 22:40
- `scripts/kitty_duel.py 150 900000` -> `server/runs/logs/q_kitty_fixed.log`
- Re-run of the banker-kitty question on code AFTER the P0 sampler fix. The
  first three attempts (21:05-21:15) are VOID: BANKER_KITTY had silently
  disabled banker search, so they measured no-search vs search.
- RESULT: 149-151 = 49.7%, Wilson95 [44.0%, 55.3%]. Not distinguishable from
  50%; ledgered in AI_POLICIES.md. Flag stays ON as true information.

## NOTES (mailbox — Air agent, read this)

- The banker world sampler was broken 21:05-21:48 today (incident
  `incidents/2026-08-03-banker-search-disabled.md`). ANY duel or battery
  started in that window is void — check your log timestamps before
  ledgering. `git pull` before launching anything new.
- New guard: `SHENGJI_STRICT_SAMPLING=1` makes a zero-world search raise
  instead of silently returning candidate 0. Both new duel scripts set it.
