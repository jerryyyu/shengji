# INC-20: R5 cache resource-cap dimension was misdiagnosed

**Date**: 2026-08-24

**Severity**: S2 — measurement-invalidating

**Status**: reconciled; the memory refusal was valid; no v9 terminal status is
claimed

## What happened

The scientific unit `belief-v2-r5-8d9390e-r2.service` ran from exact source
`8d9390e12535bbf0d235b76e81484f54f912cc86`. Its generic terminal error,
`V2 tensor cache resource cap drift`, did not identify the measured dimension.
The freeze recorded separate limits: storage
`training_bytes=68,719,476,736` (64 GiB) and host memory
`training_host_memory_bytes=25,769,803,776` (24 GiB). Exact systemd evidence
recorded `MemoryPeak=30,452,371,456`, zero swap, and no retry.

The completed physical component population totaled `27,822,677,063` bytes:

- calibration: `1,245,682,177`
- human mixture: `10,002,370,759`
- synthetic primary: `10,002,413,103`
- 50%-scale: `4,999,910,593`
- negative-control overlay: `1,572,300,431`

Therefore storage did not exceed its cap; host memory did. A later handoff
mislabeled `MemoryPeak` as artifact bytes against 24 GiB, and Codex repeated
that interpretation before reconciling the freeze, systemd, and filesystem
evidence.

## Impact

The cache refusal was interpreted as a storage/artifact-cap failure even
though the valid refusal dimension was host memory. This distorted status and
follow-up reasoning. Later memory/topology work found real issues, but
repeated full-build proofs v8/v9 cost more than necessary; this record makes
no claim about v9 terminal status.

## Detection

The error was resolved by comparing all three evidence classes: frozen cap
values, exact systemd/cgroup measurements, and physical completed-artifact
totals.

## Root and contributing causes

- The terminal refusal recorded a generic resource error without naming the
  measured and capped dimensions.
- Storage bytes and host-memory bytes were conflated in handoff/status text.
- The repeated interpretation was carried forward before the three-way
  reconciliation.
- Full-population rebuilds were used where bounded samples could have exposed
  memory/topology pressure earlier and at lower cost.

## What was valid

The `MemoryPeak` measurement exceeded the frozen host-memory cap, so the
memory refusal was valid. The physical component totals remained below the
64-GiB storage cap. The later memory/topology findings are real follow-up
issues, but they do not turn this evidence into a storage-cap overrun or a v9
terminal result.

## Prevention

1. Every resource refusal must record each named measured dimension, its cap,
   and the comparison that caused refusal.
2. Every incident reconciliation must compare freeze values,
   systemd/cgroup measurements, and physical artifact totals.
3. Completed deterministic non-test inputs should have a reusable-artifact
   route after a science-free failure, rather than requiring a full rebuild.
4. Use bounded samples to investigate sizing and topology before repeated full
   builds.
5. Keep storage and RAM caps distinct in documentation, status, and tests.

## Lesson

An unnamed resource error is not a dimension diagnosis. Resource status must
preserve the distinction between bytes stored and bytes resident in memory.
