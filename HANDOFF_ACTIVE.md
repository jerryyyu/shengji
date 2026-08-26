# Active Claude/Codex handoff

> Current operational truth and exact review asks only. Historical evidence
> belongs in HANDOFF_REVIEW.md and Git history. Do not act on an older request
> when an exact head below supersedes it.

Last reconciled: 2026-08-25 21:34 EDT.

## Immediate objective

Finish the preserved R4 cohorts through repaired calibration, one held-out test
opening, and independently reproduced terminal interpretation. Then use that
evidence to decide whether the already-prepared recoverable R5 successor should
run and whether belief merits a gameplay-search experiment. PT1 remains an
independent Mini endgame-teacher lane.

## Live execution — R4 completion-only

Claude appended the exact `e10cb3d/r3` PASS marker in canonical ledger commit
`68e4522ffa1f2a3e6e4c1048455ffc083342a723`. Codex authenticated that the
machine-generated marker was absent in its parent, present once in the review
commit, and present once on current main.

The first operator attempt refused before initialization because review/testing
had left one ignored `__init__.cpython-314.pyc` in the exact checkout. The
fresh namespace, partial, and consumption record were all absent. That one
generated file and its empty directory were removed, the failed status receipt
was preserved as
`/opt/belief-r4-completion-e10cb3d-r3.status.preinit-refusal-20260826T013147Z`,
and the exact reviewed launcher was invoked again with the authenticated review
commit. This was an operational pre-initialization refusal, not a scientific
retry and not a test opening.

The authorized run is active on Strength Cloud:

- systemd unit: `belief-r4-completion-e10cb3d-r3.service`
- evidence root: `/opt/belief-r4-completion-v1-r3`
- status: `/opt/belief-r4-completion-e10cb3d-r3.status`
- current phase at reconciliation: `calibrating`, 1/4 stages, 25%
- source: exact clean `e10cb3d3426d758f2d757d41462aba6a06bc60c8`
- freeze: `59c747be56bdd20c792608ed09be307b9661c8aff6ad7e0e720cd8156de7fea4`

Do not modify, restart, delete, or merge this lane. Its next valid transitions
are calibration publication, one held-out test opening, terminal verification,
and independent interpretation. No retraining is running or authorized.

## Review queue — one independent consolidated review

### 1. PT1 narrow repaired-head source + Mini freeze

Review PR #145 once at exact head
fc957502e32eeb418469f9daf8984122f6b89740, true parent
7068caf426cd0d0436936ad5748bb24fe4c83347. This exact r5 request supersedes
the held 7068caf/r4 packet. Carry forward the already-verified PT1
design/search/statistics and 7068caf source/freeze findings; review only the
two-file +23/-2 repair and the freshly rebound artifacts.

The repair closes the two blockers named in ledger 452af4d:

- M3: corrupting only the population manifest's internal self-hash now raises
  the exact `population manifest hash drift`; neutralizing that guard makes
  the named witness fail with DID NOT RAISE.
- M5: an internally self-consistent embedded-manifest forgery, while the
  freeze-bound file hash remains unchanged, raises the exact
  `freeze population manifest byte drift`; neutralizing that guard makes the
  named witness fail with DID NOT RAISE.
- The only production change preserves `PT1ExecutionError` before generic
  `ValueError` normalization, so M5's independent refusal remains observable.

Exact Mini artifacts:

- packet: /private/tmp/shengji-pt1-review-packet-fc95750-r5.json
  - SHA-256 c20703c8b7d19a1922d5afce6731da1e95631e4721440b3feb35976fd531a739
- byte-identical packet reopen:
  /private/tmp/shengji-pt1-review-packet-fc95750-r5.reopen.json
- population:
  /Users/jerryyu/Projects/pt1-population-manifest-fc95750-r5.json
  - SHA-256 dfa50966aa7b846a9b072a3585403249c15b80fa8026f2e277cfe644ca1ae87c
  - 416/416 natural cells
- capacity:
  /private/tmp/shengji-pt1-capacity-fc95750-r5/capacity.json
  - SHA-256 be275a82eec532541a55f3d05057afbef592a540e9ea41075896c12b8515e72f
  - 16/16 complete, ten workers, strict/native, untruncated
- rehearsal:
  /private/tmp/shengji-pt1-rehearsal-receipt-fc95750-r5.json
  - SHA-256 45b6e6a72d036ce1497ccdbd2eedd109f75b92ff6dd8428327cc528c1312425a
  - ten natural states / 40 records / 21.99s; no score/action bytes persisted
- freeze: /Users/jerryyu/Projects/pt1-freeze-fc95750-r5.json
  - SHA-256 db798bad5bd4f7a5417c3e0f66c40e459e65f3714e07bf808d94b0cdf0810ea7
- expected marker:
  /Users/jerryyu/Projects/pt1-review-marker-fc95750-r5.json
  - SHA-256 35ab3e3dad8edad0438faac9852fc659452f023a9c3ad5d6d48eeabdc6401135
- inspect-only launcher:
  /private/tmp/pt1-launch-operator-fc95750-r5.sh
  - SHA-256 6d7e5acb0a4cbb97c35ea2d96ba29271cc1c448422cabd8f00a1a179d636f93e

Full privileged-teacher battery is 112/112 pure and 112/112 strict/native;
CI server/frontend is green. Fresh evidence root
/Users/jerryyu/Projects/shengji-pt1-evidence-fc95750-r5 and the launcher
status/log slots are absent. Spent/result-free r3 remains preserved.

If clean, append the exact expected marker, comment PASS on PR #145, and
authorize one Mini initialization, scientific execution, and verification
under the fresh r5 namespace. Merge, retry, training, gameplay, strength,
promotion, and deployment remain false.

## Held, not an active review

PR #148 at exact head 7e14b529065383baee152c9dd2b8d3473627235c is
source/CI green and has a prepared R5 successor, but R5 initialization remains
held until R4 is terminally interpreted. Do not launch or repeat review work
unless the R4 result changes the final packet or Codex posts a new exact ask.

## Fleet

| host | current state | next action |
|---|---|---|
| Strength Cloud | R4 completion active; calibrating, 25% stage progress | monitor only; interpret terminal result |
| Mini | idle; PT1 repaired-head packet ready, no scientific run | launch once only after exact fc95750 PASS |
| Performance Cloud | unavailable/offline; no live R5 job | hold until R4 interpretation |
| Air | idle / not required | none |

## Authority boundaries

No active packet authorizes merge, retry, deployment, promotion, gameplay, or
a strength claim. R4 is running once under its exact marker. PT1 may initialize
once only after its exact `fc95750` marker. R5 remains held.
