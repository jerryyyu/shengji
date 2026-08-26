# Active Claude/Codex handoff

Last reconciled: 2026-08-26 11:29 EDT.

Current operational truth only. Historical evidence belongs in
`HANDOFF_REVIEW.md`. There is exactly **one active review ask**: the
consolidated R4 source+freeze review on PR #152. PT-Full has passed and is
running; do not repeat its review. Do not repeat PT1, earlier R4/R5, or
superseded freeze reviews.

## Priority 1 — live R4: monitor only

- Host/unit: `shengji-cloud` /
  `belief-r4-completion-e10cb3d-r3.service`.
- Exact source: `e10cb3d3426d758f2d757d41462aba6a06bc60c8`.
- Evidence root: `/opt/belief-r4-completion-v1-r3`.
- Latest read-only sample at 11:22 EDT: active/running, `NRestarts=0`, no
  calibration final/partial, test-attempt, terminal or terminal-partial
  artifact; about 7.6 GiB current / 19.3 GiB peak unit memory.

R4 remains inside its calibration phase. The coarse outer
progress record is not a useful within-stage ETA: outer unit 1 alone scores all
1,326 synthetic calibration rounds against four cohorts before it can increment
from 0/6. The worker remains runnable, so this is a long serial scoring unit
rather than evidence of a stall. Current ETA is roughly another 30--42 hours,
with a tighter bound only after the first population completes. The unit has no
systemd memory, swap or runtime limit; do not describe 24 GiB as a live unit
boundary. Do not signal, restart, inspect outcome-bearing calibration/test
bytes, or alter the host. When the unit terminalizes, queue one independent
terminal reconstruction and classify all cohorts from sealed evidence before
interpreting the scientific result.

Draft PR #152 is now the final exact head
`d82ba224eb59a25014b076fb07116eaa6513934a`, stacked on reviewed R4 source
`e10cb3d3426d758f2d757d41462aba6a06bc60c8`. It adds only exact-output
parallel projection for calibration/test/reconstruction, progress telemetry,
and an explicit read-only pre-test readiness gate. Neural inference and
quantization remain serial and canonical; 16 forkserver workers perform only
target-blind exact projection, and ordered reduction preserves bytes.

The immutable Perf freeze is
`/opt/belief-r4-parallel-completion-freeze-d82ba22-r1.json`, SHA-256
`3070cff6cf9d391a0ac1ed6aa0f12ee57baa8266a3103b40e70171ae69508318`.
The consolidated packet is
`/opt/belief-r4-parallel-d82ba22-freeze-inputs-r1/freeze-review-packet.json`,
SHA-256
`25caad7e79615ef7cc042c1457b11259297bc59b33aab194e82a047bf60cfa84`.
The expected marker is beside it as `expected-review-marker.txt`, SHA-256
`414163234de2eb5aa9b4ca7a5a079790c51fb09553dfe927192efe1efd88c24e`.
The destination evidence root `/opt/belief-r4-parallel-completion-v1-r1`
and its consumption tombstone are absent; no calibration or test byte has
been opened there.

### Review queue — ask A: one consolidated PR #152 source+freeze review

Review the exact head and packet once; do not split source, receipts, freeze,
or cutover into later review rounds:

1. Verify the nine-file delta against `e10cb3d`, including exact ordered
   serial/parallel parity and the `r4-verify-calibration` can-fail boundary.
   Local and exact-Perf strict selections are 75/75; CI is green. The fresh
   32-task Perf receipt is byte-identical and measures 27.94 s serial versus
   3.21 s parallel (`8.699891x`) with 16 workers.
2. Reopen the freeze and every packet input. The sealed source transfer is
   53,055,512,691 bytes / 59,495 files with file-metadata population SHA
   `95d14f9a9576de9f4bc9d0d73c8d03a33e90c62f953374c63e2201528b218add`.
   Fresh clean-head capacity is 6m33 wall / 1h39m54 CPU /
   2.4 GiB peak; deadline derivation is 3m55 wall / 16m49 CPU / 3.2 GiB peak.
   The resulting caps retain 48h wall and 24 GiB host memory.
3. Confirm the packet's disclosed fail-closed preparation events: an ignored
   duplicate native shadow, a stale pre-final-head seed registry, and a stale
   local `origin/main` were each refused before freeze/evidence initialization;
   fresh clean receipts/registry/ref were then used. A score-free review-helper
   attribute error happened only after immutable freeze publication and did
   not alter freeze bytes or initialize the evidence root.
4. Confirm the cutover contract: PASS authorizes initialization and optimized
   calibration only at first. The serial R4 stays live until optimized
   calibration completes, independently reopens, and the read-only readiness
   gate proves both test namespaces untouched. Only then may the serial unit
   stop immediately before the single optimized test opening.

If clean, append the packet's exact marker once. That one PASS is the only
review requested; it authorizes the two-phase cutover above, but no capture,
reference generation, training, retry, merge, gameplay, strength, promotion,
or deployment.

## Priority 2 — PT1 is closed as a clean negative

PT1 r7 terminal recovery at exact `0faffcd4409af3c49750a52614cb955bc0be16cf`
completed over all 416 states / 1,664 records. Claude independently rebuilt
the statistics from the sealed group bytes at canonical commits `d911e09` and
`9985eb6`; the preregistered `REFUSED` verdict is final.

- mean exact-teacher C−B: `1/208 ≈ 0.00481` versus floor `0.01`;
- bootstrap lower bound: `0`;
- positive states: `1/416` versus required 24;
- all integrity/mechanics gates passed and all authority remained false.

The exact teacher changed 1,128/1,664 actions but almost all changes were
round-value ties. This closes this late-endgame acquisition recipe; no further
PT1 review, rerun, gameplay, strength, promotion or deployment action follows.

## Priority 3 — PT-Full bounded Mini DEV run is active

PR #151 passed at canonical ledger commit `deb3ecf`; both formerly missing
N=30 mutation witnesses are now load-bearing at exact head
`c6e8d08cf9f03d341c61192e8cef3c9dcfa117d5`. The one authorized DEV run asks
the whole-play information-value question that PT1 could not: public
production A versus repeated public-world collapse A0 versus repeated exact
true world B, across 13 ranks and both partnership roles (26 roots / 52
comparison records / 130 played rounds).

Mini launchd label `com.shengji.ptfull-c6e8d08-r1` is active with PID 34778
and ten worker processes at the exact reviewed head. Output is exclusively
`/Users/jerryyu/Projects/shengji-ptfull-c6e8d08-r1.json`; progress/stdout and
stderr are the sibling `.log` and `.err.log` files. A first `nohup` delivery
attempt was terminated with zero output/progress/report bytes when its tool
shell closed; launchd repeats the identical deterministic invocation with the
same 0600 seed and output slot, so no outcome was observed or selected.

This remains DEV-only. When COMPLETE, validate the report and summarize A,
A0 and B contrasts; do not infer a scientific/strength claim or authorize
gameplay, training, promotion, deployment or merge.

## Priority 4 — prepare one recoverable, faster R5 successor; launch held

Draft PR #148 is now exact clean head
`232fc27610b9caef759179a94751308f49f8a939`. Its prior `7e14b52` / `r14c`
freeze is superseded, is not an active review request, and must not launch.
Server and frontend CI are green and the PR is mergeable. Full exact-head
BELIEF is 485 passed / 6 skipped pure and 487 passed / 4 skipped strict
compiled.

The source at #148 binds same-admission process recovery separately from retry:
sealed stages reopen, cache/training resume only from exact partial state,
completed tasks may never regenerate a missing final, failed workers and
terminal partials fail closed, and a sealed terminal can only be reconstructed.
Perf Cloud is online. Exact-head x86 recovery tests passed 73/73; the fresh
416-round/all-rank capacity receipt passed in 6m29 wall / 1h39 CPU at 2.4 GiB
peak, and the deadline receipt passed in 3m48 wall / 16m27 CPU at 3.2 GiB peak.
Those receipts opened no test data and authorize no pipeline execution.

R4 exposed one remaining performance issue before freeze: calibration/test
scoring is serial across four populations and sequential across model
predictions, leaving most cores idle. Codex is implementing and benchmarking
only deterministic round/population parallelism with byte-identical serial
parity on Perf. If source changes, the `232fc27` receipts are diagnostic only
and must be regenerated at the final head. Then generate exactly one fresh
source+freeze packet and request one consolidated review. Do not launch R5
until that packet passes and R4 has a terminally interpreted result.
