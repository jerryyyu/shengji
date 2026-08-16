# Active Claude/Codex handoff

> Coordinate current work only through this file and the append-only
> `HANDOFF_REVIEW.md`. Historical detail belongs in the archive and research
> documents; branch-local ledgers are never review or execution authority.

Last reconciled: 2026-08-16 01:52 EDT.

## Immediate objective

Finish BELIEF-V1 V2 with two remaining review boundaries:

1. one three-file accelerator delta review of PR #117; the substantive V2
   source/design packet already passed at `db0ec3e`;
2. after PASS, one exact host-specific immutable-freeze review.

No V2 pipeline execution, capture, REF-C, training, calibration, test opening,
gameplay, strength claim, promotion, or deployment is authorized now.

## Current review queue — exactly one Claude request

### P0 — PR #117, deterministic-MPS delta only

- PR: `https://github.com/jerryyyu/shengji/pull/117`
- reviewed PASS source head: `db0ec3e2f70bc4ea94229ceb872b0512f7837636`
- canonical PASS ledger: `b02ece9e549f1dbc167ce79cadeb81dbd2a500f8`
- MPS source child: `77d0b0ad9c9355cbcf13315fc477ad56ae25361e`
- exact PR head: `f915325cebb46712cc2726cc140a38513f5e63e8`
  (two-parent merge preserving the child and canonical PASS ledger)
- review mode: exact three-file delta only; do not re-open the already-PASSed
  deadline, V1 resource-reentry, or fail-closed registry findings.

Review four tightly bounded properties:

1. canonical `mps` matches PyTorch-resolved `mps:0`; CUDA indices remain exact;
2. the MPS-only one-hot batch product has the same final-event semantics and
   gradients as the indexed path, including empty histories;
3. the MPS-only ignored-label loss uses exactly the active labels with the same
   gradients; CPU/CUDA paths remain unchanged;
4. deterministic MPS training and portable CPU checkpoint export complete
   without fallback. The diagnostic selected CPU, so no GPU-retention claim is
   allowed.

Exact-head evidence:

- V2 pure: `155 passed, 1 skipped`;
- V2 compiled/strict: `156 passed`;
- accelerator plus registry focused: `15 passed`;
- isolated worker bootstrap: `BELIEF_V1_V2_BOOTSTRAP_PASS`;
- seed scan: 1,925,126 bytes, SHA-256
  `01df884daf4417479f2d713cb913ccc5f34dece035f8acf5e3acb50e505713b3`;
- registry: 1,715,217 bytes, SHA-256
  `b4e7dc190fa37734c0810b1647672340a2c771a1814217b90691271a8ff6543b`;
  5,372/5,372 candidates classified, 140 explicit, 74 finite-population,
  31 populations, 13,312 V2 seeds, zero collisions;
- all eight CPU checkpoint and epoch-receipt hashes equal `db0ec3e` exactly;
- frozen-order Mini diagnostic: CPU 2.978871292s, MPS 17.306243501s;
  gate correctly selects CPU; this is not a host-specific receipt;
- append-only review-ledger guard against `b02ece9`: PASS;
- authenticated V1 resource-failure receipt SHA-256
  `257fce06ed612a0acda356b5a55395b64a4402dc95f7461ead364c48dfa6b4a3`.

Return one delta PASS or one HOLD with every remaining blocker in this
three-file seam. A PASS preserves only host-specific capacity, device and
deadline measurement plus immutable-freeze construction. The exact frozen
packet still requires a second external PASS before execution.

## Current operational truth

- V1 design `a8c5e05f…1fd53` completed capture and REF-C. Both CPU training
  cohorts exceeded their frozen eight-hour wall cap and were stopped through
  the reviewed sequence before calibration or test. Both slots remain partial;
  the admission is spent; no model, null, calibration, terminal, or strength
  result exists. Never resume, inspect, score, or reuse the partial models.
- PR #117 remains source/design only. Parent `db0ec3e` is PASS; only the MPS
  child is pending. No evidence namespace or fleet run was initialized.
- Do not start compute merely because a host is powered on. After PR #117 PASS,
  first re-check host availability and run only the reviewed capacity/device/
  deadline measurement needed to construct the exact freeze.
- T4, S4, S6, broad Pair, Pair checkpoint, and V1 namespaces are terminal or
  spent. No retry, resume, pooling, or partial-result interpretation is open.
- PR #107 already has Codex's independent source/parity clearance. PR #116 was
  authored by Claude and is a Codex performance-review item, not a Claude queue
  item. Neither blocks PR #117.

## Next steps after MPS delta PASS

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
