# Active Claude/Codex handoff

> Current operational truth and precise review queue only. Historical review
> rounds belong in `HANDOFF_REVIEW.md` and Git history. A request not listed
> here is not active.

Last reconciled: 2026-08-25 16:30 EDT.

## Immediate objective

Produce a decision-grade answer on whether actor-visible public history
improves hidden-card ownership prediction. R4 stopped before opening test and
therefore produced no efficacy verdict. Diagnose its calibration-only
projection failure, repair the shared R4/R5 path once, then launch and
independently reproduce one recoverable R5 successor. R4 and R5 use the same
scientific population and are not independent replications.

PT1 is an isolated Mini endgame-teacher lane. Its `r3` namespace is spent at
0/416 with no result; its fresh successor remains below the belief critical
path.

## Review queue — empty pending repaired artifacts

There is no review action Claude can take yet.

- Do **not** reuse PR #147's `r13c` execution marker: exact source `2d4dfe8`
  contains the same projection bytes that just stopped R4.
- Do **not** retry PR #146 / R4 completion or PR #145 / PT1 `r3`; both exact
  one-shot namespaces are spent.
- Codex's next belief ask will be one consolidated repaired R5
  source+freeze review, with the reproduced R4 failing calibration input and
  a failing-direction projection witness bound at the new head.
- Codex's next PT1 ask will be one consolidated successor source+freeze
  review only after the natural-cell manifest and durable child-failure path
  are implemented and exercised score-free.

## Live fleet

| host | lane | state |
|---|---|---|
| Strength Cloud (`shengji-cloud`) | R4 completion | **FAILED; EVIDENCE PRESERVED; TEST UNOPENED** |
| Performance Cloud (`shengji-perf`) | R5 `r13c` | **IDLE; OLD LAUNCH HELD** |
| Mini | PT1 `r3` | **FAILED 0/416; NAMESPACE SPENT; HOST IDLE** |
| Air | none | idle / not required |

### R4 completion — calibration source failure, no scientific result

| binding | exact value |
|---|---|
| source | `721b5f8944f17718a833cfab051ff13cec1dfbfd` |
| review commit | `4cee5908880741920ef3360468f714209fd0bcc6` |
| freeze | `0d651819ad8c4e7f71bb1b7ecf8a38f1a9fe7280691886d17272f07c34c7f4f1` |
| admission | `99f0089ac7433833e2cb0af4dfe35b7a6fee3f2f8f36110ace04bb75c5df3d3c` |
| service | `belief-r4-completion-721b5f8-r1.service` |
| evidence | `/opt/belief-r4-completion-v1-r1` |

The service ran from 13:25:23 to 16:26:27 EDT: 3h01m wall, 25h50m CPU,
17,698,279,424-byte systemd peak, exit status 1, no OOM. It failed inside the
first synthetic calibration pass before publishing calibration, terminal or
test-attempt bytes:

```text
BeliefProjectionError: projection did not converge:
margin_error=0.94817366860218,
group_error=np.float64(3.6337737674418946e-06)
```

The permanent root still contains only admission, freeze, group split,
inventory and review. The test split was never opened. This is neither a
positive nor a null belief result; it is a projection/execution defect. Never
restart this service or reuse this admission.

The immediate diagnostic is calibration-only and target-safe: reproduce the
failing decision/member from preserved non-test inputs, bind its actor and raw
weight bytes, then repair the deterministic projection with a real natural
witness. Also make future scoring persist the failing decision/member and
increment progress inside a pass so another three-hour failure is observable.

### R5 `r13c` — old PASS is technically intact but operationally superseded

| binding | exact value |
|---|---|
| source | `2d4dfe84280d7c1cb433b000aa18670bf4abfdd1` |
| review commit | `9b1833312f874ad91ed43a75fd7ec5e82b83b6d1` |
| freeze | `5bfeef783ce991e385cda4eaccd4fbb5c98d2b70b5ce3c9ff7c450571680f078` |
| evidence | `/opt/belief-r5-evidence-cache-semantic-v1-r1` |

No R5 scientific service or worker is running, and the evidence/partial/
consumed namespaces remain absent. The reviewed R5 and failed R4 projection
module and test file are byte-identical (`c4603424…` and `5ee38bac…`). Launching
`r13c` would therefore risk repeating the same late calibration failure after
expensive training. The old launch command has been removed from the active
queue; do not execute it.

Reusable capture/reference/training-input/cache artifacts remain intact. The
successor should change only the shared projection/scoring observability seam,
reproduce parity and test isolation, generate one fresh exact freeze, receive
one consolidated repaired-head+freeze PASS, and launch once on Performance
Cloud.

### PT1 `r3` — no teacher result; successor not ready

| binding | exact value |
|---|---|
| source | `95a142de0f04e524c9ac0565ac8e541de26974af` |
| review commit | `59217cbbccb4b96ef197962d6e26eb8861c5941f` |
| freeze | `2352967a3a6963dc24cae05ea8ebe24bed26bac834a68ea6121d0b67a18a9860` |
| evidence | `/Users/jerryyu/Projects/shengji-pt1-evidence-95a142d-r3` |

The authenticated execution failed in its first ten-worker wave before any
of 416 groups sealed. The durable root contains freeze, deadline receipt,
empty `groups/`, and a stale `progress.json` saying `RUNNING 0/416`; the
operator status says `phase=failed`. No packet, statistics, comparison,
strength claim or gameplay artifact exists. The CLI and wrapper both lost the
child exception. Preserve the root and never retry `r3`.

A successor needs four coupled repairs before review: freeze the complete
natural-cell capture manifest before consuming the one-shot slot; persist a
sanitized per-worker failure receipt and terminal failed state; capture
launcher output; and exercise the real process pool plus natural provider on
fresh out-of-population states. Then generate a fresh capacity receipt/freeze
and request one consolidated review.

## Next actions — fixed order

1. Reproduce and diagnose R4's calibration-only projection failure without
   opening test or mutating the spent evidence root.
2. Repair the shared projection/scoring path and prepare one fresh R5 head,
   capacity/deadline receipt and freeze.
3. Request one consolidated repaired R5 source+freeze review; on PASS, launch
   exactly once on Performance Cloud.
4. Independently reproduce R5's terminal and decide whether belief advances
   into gameplay search.
5. In parallel spare bandwidth, implement the PT1 successor failure-evidence
   and natural-manifest repairs, then request one consolidated PT1 review.

## Authority boundaries

- No merge, deployment, promotion, gameplay or strength claim is authorized.
- R4 completion and PT1 `r3` may not retry; their permanent evidence roots are
  read-only forensic inputs.
- R5 `r13c` must not launch. A fresh repaired freeze and authentic review are
  required before one successor execution.
- Diagnostics must remain score-free or calibration-only; neither belief nor
  PT1 test populations may be opened outside a fresh reviewed admission.
