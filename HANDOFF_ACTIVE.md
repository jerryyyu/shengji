# Active Claude/Codex handoff

Last reconciled: 2026-08-26 11:38 EDT.

Current operational truth only. Historical evidence belongs in
`HANDOFF_REVIEW.md`. The review queue is **empty**. Do not repeat PR #152,
PT-Full, PT1, earlier R4/R5, or superseded freeze reviews.

## Priority 1 — R4 two-phase cutover: optimized calibration is live

- Host/unit: `shengji-cloud` /
  `belief-r4-completion-e10cb3d-r3.service`.
- Exact source: `e10cb3d3426d758f2d757d41462aba6a06bc60c8`.
- Evidence root: `/opt/belief-r4-completion-v1-r3`.
- Latest read-only sample at 11:38 EDT: active/running, `NRestarts=0`, no
  calibration final/partial, test-attempt, terminal or terminal-partial
  artifact; about 7.6 GiB current / 19.3 GiB peak unit memory.

The serial worker remains a fallback only. It stays live until the optimized
path has completed calibration, independently reopened it, passed the read-only
pre-test readiness gate, and proved both test namespaces untouched. Its unit
has no systemd memory, swap or runtime limit; do not describe 24 GiB as a live
unit boundary. Do not signal, restart, inspect outcome-bearing calibration/test
bytes, or otherwise alter this host before that cutover predicate is met.

PR #152 passed consolidated source+freeze review at canonical commit `394354f`.
The final exact head is
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
The optimized namespace initialized and independently verified under that
marker. Perf unit `belief-r4-parallel-completion-d82ba22-r1.service` started at
11:38 EDT with `NRestarts=0`, `MemoryMax=24 GiB`, `MemorySwapMax=0`, and
`RuntimeMaxUSec=2d`. Evidence root:
`/opt/belief-r4-parallel-completion-v1-r1`; no calibration or test output was
present at launch. This phase uses all 16 projection workers and exposes
per-population progress.

Next action is mechanical, not a new review: monitor optimized calibration;
when it seals, independently reopen it and run `r4-verify-calibration`. Only if
that passes and both serial and optimized test-attempt paths are absent, stop
the serial service immediately before the one optimized `r4-open-test`. Then
run `r4-verify-terminal` and independently classify the sealed result. No
capture, reference generation, training, retry, merge, gameplay, strength,
promotion or deployment authority follows.

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

## Priority 3 — PT-Full DEV diagnostic is complete

PR #151 passed at canonical ledger commit `deb3ecf`; both formerly missing
N=30 mutation witnesses are now load-bearing at exact head
`c6e8d08cf9f03d341c61192e8cef3c9dcfa117d5`. The one authorized DEV run asks
the whole-play information-value question that PT1 could not: public
production A versus repeated public-world collapse A0 versus repeated exact
true world B, across 13 ranks and both partnership roles (26 roots / 52
comparison records / 130 played rounds).

The immutable report is
`/Users/jerryyu/Projects/shengji-ptfull-c6e8d08-r1.json`, SHA-256
`1b404cf3eb37faf94013447b1e828bd9d030766778597cfc72780997674468a3`;
the internal report SHA is `93ad8e989401a2e7739b3fd9d6e94d609aaa9520aac3d03f32eb7f9d7bc45449`.
All 26 roots / 52 records / 130 rounds and every exact-work receipt validate.
An independent Codex reviewer reproduced the result:

- controlling B−A: `−3/52 ≈ −0.058` (10 positive / 32 tied / 10 negative);
- B−A0: `44/52 = 11/13 ≈ +0.846`;
- A0−A: `−47/52 ≈ −0.904`.

Thus the exact true world does **not** beat the ordinary public ensemble.
Repeatedly collapsing public uncertainty onto one sampled world is strongly
harmful, and B mostly recovers that collapse penalty. This is DEV-only and
does not support a hidden-information, gameplay, strength, training,
promotion, deployment or merge claim. No further PT-Full review or run is
queued.

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
