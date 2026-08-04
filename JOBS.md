# Fleet job ledger — mini (this machine)

The Air keeps its own ledger at `~/Projects/shengji-compute/JOBS.md`; its
`## NOTES` section is the inter-agent mailbox read by `fleet_status.sh`.
This file has exactly one authoritative `## RUNNING` section. A process may
start only when its immutable manifest and ledger entry already exist.

## RUNNING

*(nothing)* — deliberately. No ML generation, training, duel, T3 screen, or
high-N build is currently authorised.

## STOPPED / INVALID

- **T3 gate screen, 2026-08-04 07:43-07:48 EDT.**
  `scripts/t3_gate_screen.py 150 31000000` was launched after its preflight
  no-go and terminated with SIGTERM while consuming one full CPU core. The
  calibration/partial full-arm log and separate three-cluster JSONL smoke are
  debugging artifacts only: do not combine, extend, or interpret them.
- **v11pair vs MC blocks through 07:45.** All 4,880 rounds, including the last
  409-391 block, were launched before the call-site seeding fix. They are
  mirrored exploratory evidence, not seeded confirmation.

## NOTES (mailbox — Air agent, read this)

- `make_bot` now forwards `seed=` by factory signature. The general tournament
  helper remains incomplete: `_seeded()` still catches a blanket constructor
  `TypeError` and retries, and its repeat test compares aggregate scores rather
  than per-seed/per-flip records.
- The T3 re-entry gate and high-N prototype blockers are canonical in
  `RL_PLAN.md`. Do not substitute another run while the machine is idle.
- The banker sampler, ballot enumeration, factory seeding, and T3 runner have
  each emitted plausible-looking output through a silent fallback or invalid
  harness. Check that the intended machinery ran before reading any score.
