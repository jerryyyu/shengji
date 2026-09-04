# INC-22: Value V2 capacity compared the wrong inference artifact

**Date**: 2026-08-30

**Severity**: S3 — a reviewed capacity admission was spent, but no scientific
data, labels or outcomes were opened

**Status**: repaired at `b6d5f256`; awaiting repaired-head source/capacity
review

## What happened

The first reviewed Value V2 full-DAG capacity census at `4e60d77b` completed
its preflight, state/successor and continuation arms, then refused between the
32- and 64-item inference-batch arms. It published the canonical typed failure
receipt
`88e24ba4332b269618f92ff8652b09c23f3ba840ea81778ddc0188781da2e407`
after 577 seconds with every scientific, outcome, training and retry authority
false.

The receipt deliberately retained only the exception hash. Hashing the finite
reviewed refusal vocabulary identified the exact message:
`byte-identical fixture refusal`.

The capacity harness required raw float32 logits to be byte-identical across
batch shapes. Production inference does not seal raw logits. It already
canonicalizes softmax probabilities to six decimal places and then converts
them to exact PPB integers because equivalent matrix kernels can differ by a
few float32 ulps across batch shapes. The capacity check was therefore stricter
than—and semantically different from—the artifact it claimed to validate.

## Impact

- One reviewed score-free capacity namespace and about ten wall minutes were
  spent.
- No scientific namespace, label, outcome, audit or training artifact was
  opened or created.
- The failure prevented selection of an inference batch and therefore blocked
  the immutable V2 freeze.
- Diagnosis required source-vocabulary hash inversion because the typed
  receipt did not publish a bounded reason code for this known refusal.

## Repair

Capacity now compares the ordered production prediction representation: the
same canonical probabilities and exact PPB rows that scientific inference
would seal. Three witnesses bind the repair:

1. raw-logit ulp differences that collapse to the same sealed prediction are
   accepted;
2. a material probability change still produces a different identity; and
3. the real 32/64 capacity-arm wiring calls the repaired identity helper.

The design text now distinguishes sealed prediction identity from a
non-artifact raw-logit intermediate. Full V2 validation is 532/532 in both
pure and compiled modes; the repaired capacity-runner suite is 31/31 on the
actual Perf host.

## Prevention

1. Cross-implementation equality checks must operate at the exact artifact
   altitude consumed downstream. Internal floats may be checked separately,
   but may not silently redefine the public contract.
2. Every performance-arm witness must exercise the production wiring, not
   only a helper given already-identical arrays.
3. Equivalent-shape tests need both a permitted numerical-difference witness
   and a material-difference negative control.
4. Typed failure receipts should map known refusal classes to bounded public
   codes; hashes remain useful for integrity but should not be the sole
   diagnostic.
5. A failed capacity namespace is spent. Repair source and use a fresh
   reviewed namespace rather than relabeling the failed attempt as a retry.

## Lesson

“Byte-identical” is meaningful only after naming the bytes. Validate the
scientific artifact, not a stricter intermediate that no consumer ever sees.
