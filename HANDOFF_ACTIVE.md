# Active Claude/Codex handoff

> Current operational truth and precise review queue only. Historical review
> rounds belong in `HANDOFF_REVIEW.md` and Git history. A request not listed
> here is not active.

Last reconciled: 2026-08-25 13:50 EDT.

## Immediate objective

Produce a decision-grade answer on whether actor-visible public history
improves hidden-card ownership prediction. Finish and independently reproduce
R4, then launch and independently reproduce one efficient, recoverable R5 run.
R4 and R5 use the same scientific population and are not independent
replications. Neither run authorizes gameplay, strength, promotion, deployment
or merge.

PT1 is an isolated Mini endgame teacher screen. It cannot touch R4/R5 and is
not on their critical path.

## Review queue — empty

There is no active review ask.

- PR #146 / R4 completion received an authentic PASS at canonical-main commit
  `4cee5908880741920ef3360468f714209fd0bcc6` and is running.
- PR #147 / R5 source+freeze received its authentic consolidated PASS at
  `9b1833312f874ad91ed43a75fd7ec5e82b83b6d1` and is launch-ready.
- PR #145 / PT1 `r3` received an authentic narrow repaired-head PASS at
  `59217cbbccb4b96ef197962d6e26eb8861c5941f`; its one execution namespace is
  now spent by the worker failure below. Do not issue another PASS or retry it.

Do not review or append a marker for a proposed PT1 repair until Codex posts a
new exact source head, fresh score-free receipts/freeze and one consolidated
ask here.

## Live fleet

| host | lane | state |
|---|---|---|
| Strength Cloud (`shengji-cloud`) | R4 completion | **RUNNING** |
| Performance Cloud (`shengji-perf`) | R5 `r13c` | **READY, INTENTIONALLY HELD** |
| Mini | PT1 `r3` | **FAILED, NAMESPACE SPENT** |
| Air | none | idle / not required |

### R4 completion — running, test still unopened

| binding | exact value |
|---|---|
| source | `721b5f8944f17718a833cfab051ff13cec1dfbfd` |
| review commit | `4cee5908880741920ef3360468f714209fd0bcc6` |
| freeze | `0d651819ad8c4e7f71bb1b7ecf8a38f1a9fe7280691886d17272f07c34c7f4f1` |
| admission | `99f0089ac7433833e2cb0af4dfe35b7a6fee3f2f8f36110ace04bb75c5df3d3c` |
| service | `belief-r4-completion-721b5f8-r1.service` |
| evidence | `/opt/belief-r4-completion-v1-r1` |

The service started at 2026-08-25 13:25 EDT with `Restart=no`, 24 GiB memory,
zero swap and a 48-hour runtime ceiling. It is in the long calibration-scoring
stage (`completed=1/4`, controller stage progress 25%). The active
`r4-calibrate` worker is healthy at one full CPU core and roughly 2.6 GiB RSS.
No calibration result, durable test-attempt, terminal or test-open artifact
exists yet. The controller moves to the sole test opening only after stable
synthetic and human calibration is sealed.

On completion Codex must independently run `r4-verify-terminal`, compare the
reopened bytes with the published terminal and interpret the C/E/N/U gates.
Do not launch R5 before that interpretation.

### R5 `r13c` — reviewed and one command from launch

| binding | exact value |
|---|---|
| source | `2d4dfe84280d7c1cb433b000aa18670bf4abfdd1` |
| review commit | `9b1833312f874ad91ed43a75fd7ec5e82b83b6d1` |
| freeze | `5bfeef783ce991e385cda4eaccd4fbb5c98d2b70b5ce3c9ff7c450571680f078` |
| review packet | `771e52f8429631c32babe6e7fbf6c09c8677ebf650dcc4820cb64aa2b87b3453` |
| marker | `8237ea765d2538d99d5aaa1be7da19a861e5541f83ec5b2469317792702a1448` |
| launcher | `a534e2c464ea5f11c93ab6fde94188f7de129eaf1a1e925268085ad34d3b8274` |
| evidence | `/opt/belief-r5-evidence-cache-semantic-v1-r1` |

Live read-only preflight at 13:49 EDT reproduced the source/native/freeze and
launcher hashes. The evidence, partial, consumed-tombstone and ops namespaces
are all absent. Performance Cloud has about 403 GiB disk free and 28 GiB
available RAM. Only the systemd reference keeper is resident; no R5 worker or
scientific service is running.

R5 carries all 13 trump ranks, the human mixture, reusable capture/reference/
training-input artifacts, transparent progress and learning curves, exact
semantic cache reuse, graceful deadline truncation, a 30 GiB memory cap and a
48-hour wall cap. Launch once after R4 interpretation, then independently
reopen its terminal before any gameplay decision.

The exact one-shot outer launch envelope is fixed below. The four-day service
ceiling is deliberately outside the frozen 48-hour training-stage deadline so
deadline truncation has time to seal and the remaining terminal stages can
finish. Do not add `--collect`, restart policy, swap, or an alternate source,
review commit, evidence root, or launcher.

```sh
systemd-run --unit=belief-v2-r5-2d4dfe8-r13c \
  --property=Type=exec \
  --property=WorkingDirectory=/opt/belief-r5-index-bridge-2d4dfe8/server \
  --property=MemoryMax=32212254720 \
  --property=MemorySwapMax=0 \
  --property=RuntimeMaxSec=4d \
  --property=Restart=no \
  --property=KillMode=control-group \
  --property=TimeoutStopSec=2min \
  --property=OOMPolicy=stop \
  --property=StandardOutput=journal \
  --property=StandardError=journal \
  --setenv=PYTHONPATH= \
  /bin/bash \
  /opt/belief-r5-index-bridge-2d4dfe8-review-support-r13c/launch-r5.sh \
  9b1833312f874ad91ed43a75fd7ec5e82b83b6d1
```

### PT1 `r3` — spent at 0/416; repair not yet ready for review

| binding | exact value |
|---|---|
| source | `95a142de0f04e524c9ac0565ac8e541de26974af` |
| review commit | `59217cbbccb4b96ef197962d6e26eb8861c5941f` |
| freeze | `2352967a3a6963dc24cae05ea8ebe24bed26bac834a68ea6121d0b67a18a9860` |
| evidence | `/Users/jerryyu/Projects/shengji-pt1-evidence-95a142d-r3` |

The authenticated execution initialized at 13:47 EDT and then failed in its
first ten-worker wave before any group was sealed. The durable root contains
the exact freeze, deadline receipt, empty `groups/` and progress at 0/416; no
packet, statistics, strength claim or gameplay artifact exists. The CLI
reported only `execution worker failure; durable groups retained`, discarding
the underlying child exception. Retry is false: preserve this root and never
rerun `r3`.

Two score-free/out-of-population diagnostics used fresh unrelated secrets:

- one real `ProcessPoolExecutor` `_scientific_worker` completed end-to-end;
- ten parallel `_capture_one_state` calls completed 10/10.

That rules out a universal process-pool/native/capture failure but cannot name
the frozen child exception because `r3` failed to persist it. A successor must
at minimum: (1) freeze a complete exact natural-cell capture manifest before
opening the scientific namespace, (2) publish a sanitized durable per-worker
failure receipt, (3) exercise the real process pool and natural provider in an
out-of-population rehearsal, and (4) use a fresh freeze/admission. Keep this
below the R4/R5 critical path.

## Next actions — fixed order

1. Monitor R4 without touching its process or evidence.
2. When R4 terminalizes, independently reopen and interpret the exact result.
3. Launch the already-reviewed R5 `r13c` once, chosen with R4's evidence in
   hand; preserve all reusable non-test artifacts and graceful truncation.
4. Independently reproduce the R5 terminal and decide whether belief advances
   into gameplay search.
5. Only in parallel spare bandwidth, prepare the PT1 failure-receipt / sealed-
   population successor and post one consolidated review ask.

## Authority boundaries

- No merge, deployment, promotion, gameplay or strength claim is authorized.
- R4 and R5 may open their frozen test population exactly once under their
  authenticated admissions; PT1 `r3` may not retry.
- Main may move for append-only handoff/review records without affecting the
  detached exact source trees. Do not mutate live evidence or source bytes.
