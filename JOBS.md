# Fleet job ledger — mini (this machine)

The Air keeps its own at `~/Projects/shengji-compute/JOBS.md`; that file is
also the inter-agent mailbox (its `## NOTES` section is read by
`fleet_status.sh` every hourly check). Keep this one current: entries are
deleted when the job is done AND its result is ledgered in RL_PLAN.md or
AI_POLICIES.md, not when the process exits.

## RUNNING

### mini / v11pair vs mc block 6 — 04:35, PREREGISTERED FINAL
- `scripts/v11_extend.py mc 600 13000000` -> `runs/logs/v11_mc_block6_mini.log`
- Running on the MINI although block 6 was assigned to the Air: the Air went
  offline around 04:20. The seeds (13M) were preregistered and the duel is
  deterministic given seeds, so the machine is irrelevant to the result.
- Pooled blocks 1-5: 1478-1402 = 51.3%, n=2880, CI [49.5%, 53.1%]. This block
  takes it to ~4080. **Last extension either way.**

## NOTES` section is read by
`fleet_status.sh` every hourly check). Keep this one current: entries are
deleted when the job is done AND its result is ledgered in RL_PLAN.md or
AI_POLICIES.md, not when the process exits.

## RUNNING

### mini / v11pair vs mc block 5 — 02:10, PREREGISTERED FINAL
- `scripts/v11_extend.py mc 600 12000000` -> `runs/logs/v11_mc_block5.log`
- Air runs block 6 (seeds 13M). Pooled 1-4: 867-813 = 51.6%, n=1680,
  CI [49.2, 54.0]. Blocks 5+6 take pooled n to ~4080. **Last extension either
  way** — running until the interval clears 50 would be p-hacking.

### mini / gate duel — 02:25
- `scripts/gate_duel.py 150 5700000` -> `runs/logs/gate_duel.log`
- mc-gate-v11pair vs mc, reporting strength AND wall-clock together (the whole
  claim is near-mc strength at a fraction of the compute; either number alone
  is meaningless). Smoke: gated side ~15% of mc's per-decision cost.

## NOTES` section is read by
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

- 08-04 04:20: the Air was unreachable, so its block 6 was re-run on the mini
  with the same preregistered seeds. If the Air comes back holding a finished
  `runs/logs/v11_mc_block6.log`, the two are the SAME experiment — report one,
  do not pool them as if independent.

- The banker world sampler was broken 21:05-21:48 today (incident
  `incidents/2026-08-03-banker-search-disabled.md`). ANY duel or battery
  started in that window is void — check your log timestamps before
  ledgering. `git pull` before launching anything new.
- New guard: `SHENGJI_STRICT_SAMPLING=1` makes a zero-world search raise
  instead of silently returning candidate 0. Both new duel scripts set it.
