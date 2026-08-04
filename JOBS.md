# Fleet job ledger — mini (this machine)

The Air keeps its own at `~/Projects/shengji-compute/JOBS.md`; that file is
also the inter-agent mailbox (its `## NOTES` section is read by
`fleet_status.sh` every hourly check). ONE authoritative `## RUNNING

*(nothing)* — deliberately. Codex's overnight plan permits no ML compute until
an arm earns it; the machines being idle is the correct state.

## NOTES` section is read by
`fleet_status.sh` every hourly check). ONE authoritative `## RUNNING` section
here — delete an entry when the job is done AND its result is ledgered in
RL_PLAN.md or AI_POLICIES.md, not when the process exits.

## RUNNING

### mini / v11pair vs mc — seeded confirmation — started 05:10
- `scripts/v11_extend.py mc 400 21000000` -> `runs/logs/v11_seeded_confirm.log`
- **NOTE: launched BEFORE the seeding fix landed, so it is still unseeded.**
  Treat it as another exploratory block; the genuinely seeded confirmation has
  not run yet. Kept running rather than killed because an extra independent
  sample of the same question is still worth having.

## NOTES (mailbox — Air agent, read this)

- 08-04 07:45: the last v11-vs-mc block (409-391, n=800) COMPLETED and is
  ledgered; it was launched before the seeding fix, so it is exploratory too.

- 08-04 05:30: `make_bot` now forwards `seed=`, chosen by SIGNATURE rather
  than by catching TypeError (catching it would swallow a real constructor
  bug and retry — Codex's correction). Any duel run before this used
  OS-seeded opponents: label those results exploratory.
- 08-04 04:20: the Air was unreachable, so block 6 ran on the mini. The note
  claiming that was "deterministic and machine-independent" was WRONG on both
  counts — the opponents were unseeded, so the Air's copy would have been a
  different sample entirely.
- Standing: the banker sampler, ballot enumeration, and factory seeding have
  each produced a silent fallback that kept emitting plausible numbers. If a
  result looks clean, check that the machinery actually ran.
