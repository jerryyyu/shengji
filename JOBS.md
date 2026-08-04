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
- **Air high-N prototype, 600 states at N=240.** It finished in about 7.1
  minutes. Preserve it for debugging only: it ran without strict/pair-void
  evidence, selected and tested the winner on the same worlds, appended without
  a manifest, and has no proven raw-state round trip. It is not an unbiased
  reference, proof of a stronger teacher, or authorised training data.
- **Mini high-N corpus attempt, 20,000-state target.** Launched non-strict at
  08:09. The ledger incorrectly called it stopped while PID 22641 still held
  the file open at 99% CPU; Codex terminated parent/worker at 08:19 after 845
  JSONL rows. It inherits the prototype's validity defects and is not a
  continuation or training corpus.
- **`rl-override-v11pair-m0` vs MC.** Launched from the biased prototype refit
  and completed 235-265 (47.0%, n=500, Wilson includes 50%). The actual
  `v11_extend.py` opponent factory dropped `seed=` again, so this is an
  unseeded negative SCREEN—not a seeded rejection or a paired comparison with
  the deployed margin.

## NOTES (mailbox — Air agent, read this)

- `make_bot` and `_seeded()` now dispatch by signature and no longer catch a
  constructor `TypeError`. The general tournament helper remains incomplete:
  `_seeded()` falls through to `None` for a seedless factory whose bot has no
  `rng`, and its repeat test compares aggregate scores rather than per-seed/
  per-flip records.
- `v11_extend.py` and `gate_duel.py` still use `lambda **k: make_bot(name)`
  instead of forwarding `**k`; the current regression test does not use that
  actual factory shape. Any MC result from those call sites remains unseeded.
- The repaired T3 runner still has no real `--replay FILE` implementation,
  permits non-strict startup, omits opponent fallback counters, and cannot
  enforce `Memory.pair_void`. Do not launch it yet.
- The uncommitted `mc-race3/4-v11pair` arm is hard top-K pruning, not the
  roadmap's common-world uncertainty race. Its quoted coverage comes from the
  invalid selected-max artifact and it ignores net/candidate-generation cost.
  Do not launch or ledger it as root racing before the same re-entry gate.
- The T3 re-entry gate and high-N prototype blockers are canonical in
  `RL_PLAN.md`. Do not substitute another run while the machine is idle.
- The banker sampler, ballot enumeration, factory seeding, and T3 runner have
  each emitted plausible-looking output through a silent fallback or invalid
  harness. Check that the intended machinery ran before reading any score.
