# Active Claude/Codex handoff

> Coordinate current work only through this file and the append-only
> `HANDOFF_REVIEW.md`. Historical detail belongs in the archive and research
> documents; branch-local ledgers are never review or execution authority.

Last reconciled: 2026-08-16 02:45 EDT.

## Immediate objective

Finish BELIEF-V1 V2 with two remaining review boundaries:

1. one consolidated accelerator/CPU/deadline-freeze delta review of PR #117;
   the substantive V2 source/design packet already passed at `db0ec3e`;
2. after PASS, one exact host-specific immutable-freeze review.

No V2 pipeline execution, capture, REF-C, training, calibration, test opening,
gameplay, strength claim, promotion, or deployment is authorized now.

## Current review queue — exactly one Claude request

### P0 — PR #117, runnable-freeze delta

- PR: `https://github.com/jerryyyu/shengji/pull/117`
- reviewed PASS source head: `db0ec3e2f70bc4ea94229ceb872b0512f7837636`
- canonical PASS ledger: `b02ece9e549f1dbc167ce79cadeb81dbd2a500f8`
- exact PR head: `1a0c9c8509aa93ad1b72e7718c5b7515c5f189b7`
- immediate parent: `f915325cebb46712cc2726cc140a38513f5e63e8`
- exact review prompt:
  `https://github.com/jerryyyu/shengji/pull/117#issuecomment-5306143775`
- review mode: one consolidated delta PASS/HOLD; do not re-open the already
  PASSed V1 resource-reentry, in-loop stage deadlines, or fail-closed registry.

Review four tightly bounded properties together:

1. canonical `mps` matches PyTorch-resolved `mps:0`; CUDA indices remain exact;
   both MPS-only math repairs preserve semantics/gradients and CPU/CUDA paths;
2. an explicit CPU candidate is legal only with no supported accelerator,
   re-probes that absence, and runs one warmup plus three deterministic
   measured CPU arms without inventing an accelerator comparison;
3. the new deadline producer reopens all 416 capture samples, measures 32
   all-rank REF-C rounds under proven 16-worker overlap, runs two repeatable
   eight-member training probes, and derives the epoch/reserve mechanically;
4. preflight, deadline, selected device, and freeze all bind to the same
   hostname, boot, 16 CPUs, memory, Python/native bytes, and source. Mini or a
   different host/boot cannot inherit the receipt.

Exact-head evidence:

- V2 pure: `163 passed, 1 skipped`;
- V2 compiled/strict: `164 passed`;
- registry focused: `7 passed`;
- isolated worker bootstrap: `BELIEF_V1_V2_BOOTSTRAP_PASS`;
- deadline-probe schedule SHA-256
  `0c03e2c9497d8e26bb5b8ae3119e54f7f9fe8490e6d1b400cd8d4f8126f471bb`;
- seed scan: 1,933,880 bytes, SHA-256
  `dd5776b13ff82b449c1dd4bcb31aaefdff48abe3fdf5db75065d28dcc6443c9c`;
- registry: 1,721,217 bytes, SHA-256
  `83df2c13a4f6700139936e8e3bea72fc72810bb7e3004188048fd6ed2730e3d1`;
  5,396/5,396 candidates classified, 135 explicit-required,
  74 finite-population,
  31 populations, 13,312 V2 seeds, zero collisions;
- frozen-order Mini diagnostic: CPU 2.978871292s, MPS 17.306243501s;
  gate correctly selects CPU; this is not a host-specific receipt;
- diff-check, clean-tree and append-only review-ledger guards: PASS.

Return one delta PASS or one HOLD with every remaining blocker. A PASS
authorizes only a fresh exact-head capacity preflight, score-free deadline/
device measurement, and immutable-freeze construction. The exact frozen packet
still requires a second external PASS before execution.

## Current operational truth

- V1 design `a8c5e05f…1fd53` completed capture and REF-C. Both CPU training
  cohorts exceeded their frozen eight-hour wall cap and were stopped through
  the reviewed sequence before calibration or test. Both slots remain partial;
  the admission is spent; no model, null, calibration, terminal, or strength
  result exists. Never resume, inspect, score, or reuse the partial models.
- PR #117 remains source/design only. Parent `db0ec3e` is PASS; the consolidated
  runnable-freeze child is pending. No evidence namespace or fleet run was
  initialized.
- Do not start compute merely because a host is powered on. After PR #117 PASS,
  first re-check host availability and run only the reviewed capacity/device/
  deadline measurement needed to construct the exact freeze.
- T4, S4, S6, broad Pair, Pair checkpoint, and V1 namespaces are terminal or
  spent. No retry, resume, pooling, or partial-result interpretation is open.
- PR #107 already has Codex's independent source/parity clearance. PR #116 was
  authored by Claude and is a Codex performance-review item, not a Claude queue
  item. Neither blocks PR #117.

## Next steps after runnable-freeze delta PASS

1. Select one available host with at least 16 logical CPUs; Mini does not
   qualify for the all-lane capacity preflight.
2. At exact reviewed source, produce the H0/preflight, runtime/native/boot,
   candidate-device/memory, deadline-estimate, resource-cap, seed scan/registry,
   V1 failure, and cohort-schedule bindings.
3. Build one canonical immutable freeze in a fresh unused namespace. Do not
   initialize it.
4. Request one exact-freeze review. Only its authentic PASS marker can admit
   the one-shot offline pipeline.
5. During the delta-review wait, further profiling must stay in a separate
   worktree and must not mutate PR #117 or historical evidence. It carries no
   strength authority.

## Durable references

- Scientific plan and current milestone: `RL_PLAN.md`
- Ordered research/output ledger: `BACKLOG.md`
- Stable operational rules: `AI_POLICIES.md`
- Exact BELIEF contracts: `BELIEF_V1_SPEC.md`, `BELIEF_V1_V2_DESIGN.md`
- Lossless verdict/authority ledger: `HANDOFF_REVIEW.md`
- Historical handoff snapshots: `docs_archive/`
