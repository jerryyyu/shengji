# INC-17: A Codex request template looked like an independent review PASS

**Date**: 2026-08-12, 16:55–20:06 EDT

**Severity**: S4 — authority near-miss caught before impact

**Status**: contained; no implementation or execution crossed the gate

## What happened

The Codex-authored S5 census review request included the proposed marker as a
literal line at column one:

```text
S5_POINT_PROTECTION_CENSUS_V1_REVIEW {...}
```

Column one is reserved for independently generated reviewer markers. A scan
using the correct S5 prefix therefore found exactly one apparent PASS even
though Claude had not reviewed or reproduced the census. The surrounding
heading still said `Codex`, which exposed the mismatch before any treatment
code or run was authorized.

The same check found a second ambiguity: the Pair V3 source-population request
named its JSON schema but did not declare the literal marker prefix a reviewer
should emit.

## Impact

- No S5 treatment was implemented or executed under the false marker.
- No job, evidence read, training, promotion or deployment was authorized.
- All 32 fleet cores continued their already-reviewed strength work.
- The reviewer still has to recompute S5 before the lane may advance.

## Root cause

Two individually reasonable conventions were not enforced together:

1. request text said raw PASSes belong at column one, but the request template
   itself was not indented; and
2. the consumer checked prefix position/count without also authenticating the
   author context immediately preceding the marker.

A marker-looking line is not independent evidence merely because it is
well-formed JSON at column one.

## Containment

1. Indented the malformed S5 request template.
2. Re-ran exact column-one scans and confirmed no S5 reviewer marker exists.
3. Appended a canonical correction without granting authority.
4. Fixed the Pair source prefix to
   `PAIR_BALLOT_AFFECTED_SOURCE_POPULATION_V1_REVIEW` before review.
5. Left S5 implementation and all Pair merge/evaluation actions closed.

## Prevention

1. Every request must indent marker templates and name one literal prefix.
2. Authentication requires all three checks: exactly one column-one prefix,
   an immediately preceding independent-reviewer heading, and exact JSON field
   and byte bindings.
3. A prefix count alone is never sufficient, even when it equals one.
4. Any future ledger linter should reject a raw marker beneath a Codex request
   heading while permitting the explicitly retained authority block at the top
   of the compacted ledger.

## Lesson

**Authority is provenance plus content, not syntax alone.** A byte-perfect
template written by the implementer is still only a request until the
independent reviewer reproduces it.
