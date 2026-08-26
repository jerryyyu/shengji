# Active Claude/Codex handoff

> Current operational truth and exact review asks only. Historical evidence
> belongs in HANDOFF_REVIEW.md and Git history. Do not act on an older request
> when an exact head below supersedes it.

Last reconciled: 2026-08-25 21:12 EDT.

## Immediate objective

Finish the preserved R4 cohorts through repaired calibration, one held-out test
opening, and independently reproduced terminal interpretation. Then use that
evidence to decide whether the already-prepared recoverable R5 successor should
run and whether belief merits a gameplay-search experiment. PT1 remains an
independent Mini endgame-teacher lane.

## Review queue — two independent consolidated reviews

### 1. Top priority: R4 completion-only source + freeze

Review PR #146 once at exact head
e10cb3d3426d758f2d757d41462aba6a06bc60c8. This r3 route supersedes the
a5e06a7/r2 request; do not append or use the old r2 marker.

Exact Strength Cloud artifacts:

- freeze: /opt/belief-r4-completion-freeze-e10cb3d-r3.json
  - SHA-256 59c747be56bdd20c792608ed09be307b9661c8aff6ad7e0e720cd8156de7fea4
- packet:
  /opt/belief-r4-completion-e10cb3d-freeze-inputs-r3/freeze-review-packet.json
  - SHA-256 afc7374933ec6fd6d100061da3a7ec79f9b56bd3c14e6d18efc72a449d364d8e
- byte-identical packet reopen:
  /opt/belief-r4-completion-freeze-review-packet-e10cb3d-r3.reopen.json
- expected marker:
  /opt/belief-r4-completion-e10cb3d-freeze-inputs-r3/expected-review-marker.txt
  - SHA-256 d4bd42f70bf4e545d7aa0cc7f547402fcffdad3d5fbb25925354dbe53b5c0709
- inspect-only launcher:
  /opt/belief-r4-completion-e10cb3d-review-support-r3/launch-r4-completion.sh
  - SHA-256 a5008eb0846138748aa4be882515b4ac90bc29a1c5d22ea7028d620e03d2f3e7
- launch manifest:
  /opt/belief-r4-completion-e10cb3d-review-support-r3/launch-manifest.json
  - SHA-256 731f558c3a5dc64ff1c7a2c38f25020cc5f6e725616fff5897128707548e88e4

The inherited a5e06a7 projection repair is unchanged. The five-file e10cb3d
delta makes admission completion-only. Authority permits calibration, one test
opening, and terminal reconstruction; capture, reference generation, training,
retry, sampler, gameplay, strength, promotion, deployment, and merge are false.

Fresh exact-head capacity completed 416/416 diverse-rank rounds at 16 lanes.
The exact execution venv imports the e10cb3d tree. The fresh r3 evidence,
partial, and consumed paths are absent. Original R4 and spent r1/r2 evidence
remain immutable and test-unopened.

If clean, append the exact expected marker to canonical HANDOFF_REVIEW.md,
comment PASS on PR #146, and authorize exactly one r3 initialization,
calibration, held-out test opening, and terminal verification.

### 2. Parallel: PT1 successor source + Mini freeze

Review PR #145 once at exact head
7068caf426cd0d0436936ad5748bb24fe4c83347. Do not retry spent/result-free
95a142d/r3 and do not reopen settled PT1 design/statistics questions.

Exact Mini artifacts:

- packet: /private/tmp/shengji-pt1-review-packet-7068caf-r4.json
  - SHA-256 83a31214757eb7314a17379fa2c69e72f392ca6e633e45045d1a419d114b8fd6
- population:
  /Users/jerryyu/Projects/pt1-population-manifest-7068caf-r4.json
  - SHA-256 5ef579d2e052b28a9202478499c29fb934f539158e2620de92b22b34622d0e7f
- capacity:
  /private/tmp/shengji-pt1-capacity-7068caf-r4/capacity.json
- freeze: /Users/jerryyu/Projects/pt1-freeze-7068caf-r4.json
- expected marker:
  /Users/jerryyu/Projects/pt1-review-marker-7068caf-r4.json
- inspect-only launcher:
  /private/tmp/pt1-launch-operator-7068caf-r4.sh

If clean, append the exact marker, comment PASS on PR #145, and authorize one
Mini initialization, scientific execution, and verification under the fresh r4
namespace. Merge, retry, training, gameplay, strength, promotion, and
deployment remain false.

## Held, not an active review

PR #148 at exact head 7e14b529065383baee152c9dd2b8d3473627235c is
source/CI green and has a prepared R5 successor, but R5 initialization remains
held until R4 is terminally interpreted. Do not launch or repeat review work
unless the R4 result changes the final packet or Codex posts a new exact ask.

## Fleet

| host | current state | next action |
|---|---|---|
| Strength Cloud | idle after fresh R4 r3 preflight/freeze | launch completion only after R4 PASS |
| Mini | idle; PT0 complete, PT1 not running | launch PT1 only after PT1 PASS |
| Performance Cloud | unavailable/offline; no live R5 job | hold until R4 interpretation |
| Air | idle / not required | none |

## Authority boundaries

No active packet authorizes merge, retry, deployment, promotion, gameplay, or
a strength claim. R4 and PT1 may each initialize only once after their own
exact marker. R5 remains held.
