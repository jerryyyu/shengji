# BELIEF-V1 B2 Mini runbook

Status: pre-execution operational procedure. This document grants no authority.
The exact merged source, host-specific design, and external marker remain the
only admission chain.

## Purpose

Run the complete BELIEF-V1 B2 offline milestone through one detached,
fail-stop sequence:

1. initialize the reviewed one-shot namespace;
2. run all 16 deterministic capture lanes;
3. run all 16 deterministic REF-C lanes;
4. train the candidate and permuted-label cohorts;
5. consume the single test-decision opening;
6. independently reopen the terminal artifact.

This is score-free offline calibration work. It cannot run online sampling or
gameplay and cannot authorize strength, promotion, or deployment.

## Preconditions

All items are mandatory and are checked again immediately before launch:

- PR #113 has an exact-head external source PASS and is merged without
  changing reviewed BELIEF source/design bytes.
- A fresh detached Mini checkout exists at the exact merge commit. It is clean,
  contains no bytecode/import shadows, and has exactly one locally built native
  `_fast` extension.
- `python -P -B server/scripts/belief_v1_b2.py --bootstrap-check-only` prints
  only `BELIEF_V1_B2_BOOTSTRAP_PASS` under the required environment.
- A fresh design is frozen from that checkout into an unused absolute sibling
  path beside the unused evidence root.
- The design is mode `0400`, one link, and its SHA-256 is independently
  recorded. Its source/runtime/boot/native bindings reopen exactly.
- Canonical main contains exactly one authentic Claude marker for that exact
  design. The marker review explicitly covers the detached command schedule
  below.
- The evidence root, `.partial` path, and `.consumed.json` tombstone are all
  absent. No older BELIEF namespace is reused.
- Mini has at least 10 logical CPUs, 16 GiB physical memory, and 32 GiB free
  storage. No scored or other research worker owns the host.

Required environment for every controller process:

```text
PYTHONDONTWRITEBYTECODE=1
PYTHONHASHSEED=0
SHENGJI_FAST=1
SHENGJI_REQUIRE_VOIDS=1
PYTHONPATH absent
```

## Frozen launch variables

The design review fills and quotes these literal values; no unresolved command
substitution, glob, or broad path is permitted in the launched command:

```text
SOURCE_CHECKOUT=<absolute clean detached checkout>
EXECUTION_GIT=<exact merge commit>
DESIGN_PATH=<absolute immutable design.json>
DESIGN_SHA256=<exact SHA-256>
EVIDENCE_ROOT=<absolute unused evidence directory>
REVIEW_COMMIT=<exact canonical Claude marker commit>
SEALED_LOG=<absolute unused mode-0600 supervisor log>
```

The source checkout and evidence paths must live under explicit task-specific
directories. Never use `$HOME`, `~`, the repository root, or `/private/tmp` as
an evidence deletion/cleanup target.

## Stage schedule

The reviewed detached supervisor performs the following logical sequence. The
literal invocation uses the checkout's frozen virtual-environment Python with
`-P -B`; it does not use a mutable shell alias.

```text
initialize --design DESIGN_PATH --expected-design-sha256 DESIGN_SHA256 \
  --review-commit REVIEW_COMMIT

capture-lane --root EVIDENCE_ROOT --lane 0..15     [parallel, exactly once]
reference-lane --root EVIDENCE_ROOT --lane 0..15  [parallel, exactly once]

train-cohort --root EVIDENCE_ROOT --kind candidate
train-cohort --root EVIDENCE_ROOT \
  --kind hard-geometry-label-permutation           [parallel, exactly once]

open-test --root EVIDENCE_ROOT                     [exactly once]
verify-terminal --root EVIDENCE_ROOT               [read-only reconstruction]
```

The supervisor records each child PID, stage, lane/kind, start, exit status,
and finish in the sealed log. It waits for every child in a parallel stage and
advances only if every exit status is zero. Any signal, missing child, nonzero
exit, cap refusal, or artifact refusal stops the sequence. It never retries a
lane, cohort, initialization, or test opening.

The training cohorts may run together because each process is pinned to one
Torch thread and the frozen resource receipt sums device time while measuring
parallel wall span. If the exact design review instead serializes them, that
order becomes immutable for this run; it is not changed after admission.

## Monitoring boundary

During execution, operators may inspect only:

- supervisor and child PID/process state;
- CPU, memory, disk occupancy, and load;
- existence, permissions, link count, byte count, and mtime of expected paths;
- the supervisor's score-free stage/lane exit-status ledger, if the exact
  design review explicitly declares that ledger safe.

Do not read capture rows, target rows, reference worlds, checkpoints, test
outputs, `terminal/result.json`, or the controller's terminal-decision stdout
before the terminal-review protocol permits it. The sealed log is not tailed.

## Terminal routing

- Any nonzero stage leaves the namespace and tombstone in place for read-only
  failure review. It does not retry or continue to a later stage.
- A completed `verify-terminal` still grants no interpretation by itself.
  Claude independently reopens the exact terminal bytes and records the
  terminal verdict on canonical main.
- `SELECT_NONE_NO_CALIBRATION_LIFT` closes this exact learning recipe.
- `SELECT_NONE_BEHAVIORAL_CLAIM_UNSUPPORTED` closes the behavioral claim.
- Any `REFUSE_*` outcome preserves the artifacts for diagnosis and grants no
  retry.
- `PASS_TO_B3_SAMPLER_IMPLEMENTATION_REVIEW` opens only a B3 source/design
  milestone. It does not authorize sampler execution, gameplay, strength,
  promotion, or deployment.

## After terminal review

Keep the exact source checkout, design, tombstone, evidence root, sealed log,
and review commit until the terminal record and required hashes are preserved
canonically. Cleanup is a separate explicit operation; this runbook contains
no deletion command.
