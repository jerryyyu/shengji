# Active Claude/Codex handoff

> Current operational truth and exact review asks only. Historical evidence
> belongs in `HANDOFF_REVIEW.md` and Git history. Do not repeat a superseded
> review. There is exactly one active review ask below.

Last reconciled: 2026-08-25 22:04 EDT.

## Immediate objective

1. Leave the live R4 completion run untouched through calibration, one held-out
   test opening, terminal verification, and independent interpretation.
2. Perform one narrow PT1 repaired-head review; if PASS, append its exact marker
   so Codex can launch the one authorized Mini execution.
3. Keep R5 held until R4 is terminally interpreted and a final packet binds
   that result. R4 and R5 share one population and are not independent
   replications.

## Live execution — R4 completion-only

R4 requires no further source/freeze review and is already active on Strength
Cloud under the exact `e10cb3d/r3` PASS marker in canonical ledger commit
`68e4522ffa1f2a3e6e4c1048455ffc083342a723`.

- unit: `belief-r4-completion-e10cb3d-r3.service`
- source: `e10cb3d3426d758f2d757d41462aba6a06bc60c8`
- freeze SHA-256:
  `59c747be56bdd20c792608ed09be307b9661c8aff6ad7e0e720cd8156de7fea4`
- evidence: `/opt/belief-r4-completion-v1-r3`
- status: `/opt/belief-r4-completion-e10cb3d-r3.status`
- current phase: `calibrating`, 1/4 stages, 25%
- health at reconciliation: active/running, `NRestarts=0`, test unopened;
  `MemoryCurrent=MemoryPeak=12,941,238,272` bytes

The first launcher invocation refused before initialization because review
testing left one ignored `.pyc`; the evidence root and one-shot slot were
absent. Its receipt is preserved. The exact reviewed launcher then started the
single authorized run. Do not modify, restart, delete, merge, or infer a result
from operational progress. The only valid next transitions are calibration
publication, one test opening, terminal verification, and independent review.

## Review queue — exactly one narrow review

### PT1 canonical-provenance repair + fresh Mini `r6` freeze

Review PR #145 once at exact head
`e27240e46981cae9db099236113a2b655d88570c`, true parent
`fc957502e32eeb418469f9daf8984122f6b89740`. Carry forward the exact
`fc95750/r5` PT1 design/search/statistics and source/freeze PASS. Review only
the two-file `+6/-1` delta and freshly rebound artifacts; do not reopen settled
surfaces.

Why the prior PASS cannot launch: the exact `fc95750/r5` launcher reached the
real initialization command but refused with `review marker provenance
unavailable`. It completed 0/3 operator stages, created no evidence root, and
opened no scientific/test/score bytes. The source's canonical GitHub URL had a
one-character repository-owner typo. This was a pre-initialization refusal, so
no scientific slot was consumed and no retry is being requested.

The repaired head:

- corrects only `CANONICAL_REMOTE_URL` to
  `https://github.com/jerryyu/shengji.git`;
- adds `test_review_provenance_uses_the_canonical_repository_url`, which pins
  that exact production literal;
- fails that named witness when the bad literal is restored;
- authenticates the already-PASSed `fc95750/r5` marker and review commit live
  through the repaired production path;
- passes 113/113 privileged-teacher tests in pure and strict/native modes;
- has green server/frontend CI and a clean exact checkout.

One byte-reproduced packet binds the complete ask:

- packet:
  `/private/tmp/shengji-pt1-review-packet-e27240e-r6.json`
  - SHA-256
    `20d69d00c06ae4c5ff744cf60723d2f0f2880113c1ada2d9259985fcbe0ba0fd`
- byte-identical reopen:
  `/private/tmp/shengji-pt1-review-packet-e27240e-r6.reopen.json`
- freshly regenerated 416/416 natural-state population:
  `/Users/jerryyu/Projects/pt1-population-manifest-e27240e-r6.json`
  - SHA-256
    `dfa50966aa7b846a9b072a3585403249c15b80fa8026f2e277cfe644ca1ae87c`
  - byte-identical to the prior population because capture semantics and the
    unspent scientific secret did not change
- fresh Mini capacity:
  `/private/tmp/shengji-pt1-capacity-e27240e-r6/capacity.json`
  - SHA-256
    `35957f033e8d038e69e29174b95fa87e1b0b767ed8b6eb4cc7db1b102dc7bce1`
  - 16/16 complete, ten workers, strict/native, untruncated
- capacity manifest:
  `/private/tmp/shengji-pt1-capacity-e27240e-r6/manifest.json`
  - SHA-256
    `058fbc9b367a41f7a129a5aee80daea6d18d58d7e1a52af50ab415db005ef857`
- fresh ten-state/40-record rehearsal:
  `/private/tmp/shengji-pt1-rehearsal-receipt-e27240e-r6.json`
  - SHA-256
    `3cd6b4a75a52e6e5096fd99b5bf6323b5c7de8a70b195dbf4bc317b01082df0a`
  - 19.55 seconds, no score/action bytes persisted
- freeze:
  `/Users/jerryyu/Projects/pt1-freeze-e27240e-r6.json`
  - SHA-256
    `64352206b3e930eefa431c3b358356915bd5cb65708d0056c7711b7ef367d8dc`
  - deadline `930,722,524,358` ns, ten workers, same-namespace resume only
- expected marker:
  `/Users/jerryyu/Projects/pt1-review-marker-e27240e-r6.json`
  - SHA-256
    `14abd7e247c137f3869761375959412ffd79e3d9009ec08470acf4b4030d5502`
- inspect-only launcher:
  `/private/tmp/pt1-launch-operator-e27240e-r6.sh`
  - SHA-256
    `7974bf9064358ffac8bc7a8d86fda146b614de523b5676ec1159fb3955f1b0a4`

The fresh evidence root and `r6` launcher status/log slots are absent. The old
`fc95750/r5` refusal log is preserved, and spent/result-free `95a142d/r3`
remains immutable at 0/416.

If and only if the narrow repair and fresh bindings pass, append the exact
expected marker at column 1, comment PASS on PR #145, and authorize one Mini
initialization, scientific execution, and verification under
`/Users/jerryyu/Projects/shengji-pt1-evidence-e27240e-r6`. No merge, retry,
training, gameplay, strength, promotion, or deployment authority follows.

## Held — not an active review

PR #148 at exact head `7e14b529065383baee152c9dd2b8d3473627235c`
is source/CI green and has a prepared R5 successor. Do not launch or repeat its
old review. After R4 terminal interpretation, Codex will rebuild one final R5
packet that explicitly binds the R4 completion result and independent terminal
review. Performance Cloud is offline and is not currently needed.

## Fleet

| host | current state | next action |
|---|---|---|
| Strength Cloud | R4 completion active; calibrating at 25% stage progress | monitor only; interpret terminal result |
| Mini | idle after fresh PT1 score-free artifacts | launch PT1 once after exact `e27240e/r6` PASS |
| Performance Cloud | offline; no R5 job | hold until R4 interpretation |
| Air | idle / not required | none |

## Authority boundaries

No active packet authorizes merge, retry, deployment, promotion, gameplay, or
a strength claim. R4 is already running once under its exact marker. PT1 may
initialize once only after its exact `e27240e/r6` marker is appended by an
authentic review commit. R5 remains held.
