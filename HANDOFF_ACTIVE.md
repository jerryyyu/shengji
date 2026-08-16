# Active Claude/Codex handoff

> Coordinate current work only through this file and the append-only
> `HANDOFF_REVIEW.md`. Historical detail belongs in the archive and research
> documents; branch-local ledgers are never review or execution authority.

Last reconciled: 2026-08-16 01:22 EDT.

## Immediate objective

Finish BELIEF-V1 V2 with two remaining review boundaries, not a sequence of
piecemeal reviews:

1. one consolidated exact-head source/design review of PR #117;
2. after PASS, one exact host-specific immutable-freeze review.

No V2 pipeline execution, capture, REF-C, training, calibration, test opening,
gameplay, strength claim, promotion, or deployment is authorized now.

## Current review queue — exactly one Claude request

### P0 — PR #117, consolidated V2 resource-reentry repair

- PR: `https://github.com/jerryyyu/shengji/pull/117`
- previously reviewed HOLD head: `0949404f439189fca575ea59911c6e3fbde66277`
- fail-closed registry child: `cc3b491ec2fc8b5da29299d82c6e24bf193cfdf4`
- repaired source commit: `08c852d77bb360a193c49adfba483b1feb3a09b6`
- superseding exact PR head: `db0ec3e2f70bc4ea94229ceb872b0512f7837636`
  (two-parent merge with current canonical main `06ca3e42b64476d75a7217716c148f915becc049`;
  reviewed V2 ancestry is preserved without squash)
- review mode: delta review from `0949404` plus exact-head reconstruction;
  do not re-open findings already closed at the reviewed parent unless the
  repair changed their bytes or dependency surface.

Review the three prior HOLD findings as one packet:

1. **Live deadline:** measured next-unit/epoch estimates and reserve are frozen;
   synthetic capture/reference, device qualification and training check the
   monotonic deadline inside their loops. Expiry durably records exact refusal
   bytes, cannot advance or seal, blocks calibration and the sole test opener,
   and cannot retry the occupied slot under the same admission.
2. **Narrow V1 resource-failure route:** exact route
   `RESOURCE_FAILURE_REPAIRED_FOR_NEW_V2_FREEZE_REVIEW` authenticates the spent
   V1 admission, Claude-reviewed stop, canonical ledger ancestry, exact two
   partial training slots, frozen-cap overrun, and absence of calibration/test/
   terminal/model results. It is not V1 PASS or SELECT_NONE and grants no
   execution authority.
3. **Fail-closed seed registry:** every explicit-required source candidate must
   have an exact reviewed identity. The permanent
   `NEW_SCREEN_POPULATION_SEED_START` mutation must refuse rather than receive
   an inferred classification.

Exact-head evidence:

- V2 pure: `153 passed, 1 skipped`;
- V2 compiled/strict: `154 passed`;
- registry suite: `7 passed`;
- isolated worker bootstrap: `BELIEF_V1_V2_BOOTSTRAP_PASS`;
- seed scan: 1,923,736 bytes, SHA-256
  `d8f9e386751dce5c76e04c9b7b6693d471dc30cbaf1dfbb4a4a322c70bc476a3`;
- registry: 1,714,713 bytes, SHA-256
  `13bd632c13e7f4723c9211a62986077f8b7c893f7609012622effd5298d8669d`;
  5,370/5,370 candidates classified, 140 explicit, 74 finite-population,
  31 populations, 13,312 V2 seeds, zero collisions;
- append-only review-ledger guard against current main: PASS;
- authenticated V1 resource-failure receipt SHA-256
  `257fce06ed612a0acda356b5a55395b64a4402dc95f7461ead364c48dfa6b4a3`.

Return one verdict: PASS or HOLD with all remaining source/design blockers in a
single response. A PASS authorizes only host-specific capacity, device and
deadline measurement plus immutable-freeze construction. The exact frozen
packet still requires a second external PASS before execution.

## Current operational truth

- V1 design `a8c5e05f…1fd53` completed capture and REF-C. Both CPU training
  cohorts exceeded their frozen eight-hour wall cap and were stopped through
  the reviewed sequence before calibration or test. Both slots remain partial;
  the admission is spent; no model, null, calibration, terminal, or strength
  result exists. Never resume, inspect, score, or reuse the partial models.
- PR #117 is source/design only. It has not initialized an evidence namespace
  or used a fleet host.
- Do not start compute merely because a host is powered on. After PR #117 PASS,
  first re-check host availability and run only the reviewed capacity/device/
  deadline measurement needed to construct the exact freeze.
- T4, S4, S6, broad Pair, Pair checkpoint, and V1 namespaces are terminal or
  spent. No retry, resume, pooling, or partial-result interpretation is open.
- PR #107 already has Codex's independent source/parity clearance. PR #116 was
  authored by Claude and is a Codex performance-review item, not a Claude queue
  item. Neither blocks PR #117.

## Next steps after source PASS

1. Select one available host with at least 16 logical CPUs; Mini does not
   qualify for the all-lane capacity preflight.
2. At exact reviewed source, produce the H0/preflight, runtime/native/boot,
   candidate-device/memory, deadline-estimate, resource-cap, seed scan/registry,
   V1 failure, and cohort-schedule bindings.
3. Build one canonical immutable freeze in a fresh unused namespace. Do not
   initialize it.
4. Request one exact-freeze review. Only its authentic PASS marker can admit
   the one-shot offline pipeline.
5. During the source-review wait, performance profiling may proceed in a
   separate worktree/host only; it must not mutate PR #117 or historical
   evidence and carries no strength authority.

## Durable references

- Scientific plan and current milestone: `RL_PLAN.md`
- Ordered research/output ledger: `BACKLOG.md`
- Stable operational rules: `AI_POLICIES.md`
- Exact BELIEF contracts: `BELIEF_V1_SPEC.md`, `BELIEF_V1_V2_DESIGN.md`
- Lossless verdict/authority ledger: `HANDOFF_REVIEW.md`
- Historical handoff snapshots: `docs_archive/`
