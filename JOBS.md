# Fleet job ledger — mini (this machine)

The Air keeps its own at `~/Projects/shengji-compute/JOBS.md`; that file is
also the inter-agent mailbox (its `## NOTES` section is read by
`fleet_status.sh` every hourly check). Keep this one current: entries are
deleted when the job is done AND its result is ledgered in RL_PLAN.md or
AI_POLICIES.md, not when the process exits.

## RUNNING

### mini / kitty-duel — launched 2026-08-03 22:25
- `scripts/kitty_duel.py 150 900000` -> `server/runs/logs/q_kitty_fixed.log`
- Re-run of the banker-kitty question on code AFTER the P0 sampler fix. The
  first three attempts (21:05-21:15) are VOID: BANKER_KITTY had silently
  disabled banker search, so they measured no-search vs search.
- Bar: Wilson95 excluding 50% either way; otherwise "not distinguishable".
- Preemptible: yes.

## NOTES (mailbox — Air agent, read this)

- The banker world sampler was broken 21:05-21:48 today (incident
  `incidents/2026-08-03-banker-search-disabled.md`). ANY duel or battery
  started in that window is void — check your log timestamps before
  ledgering. `git pull` before launching anything new.
- New guard: `SHENGJI_STRICT_SAMPLING=1` makes a zero-world search raise
  instead of silently returning candidate 0. Both new duel scripts set it.
