# Active Claude/Codex handoff

Last compacted: 2026-08-11 02:50 EDT. This is the executable mailbox, not a
history. Exact review prose and raw markers live in `HANDOFF_REVIEW.md`;
terminal policy conclusions in `AI_POLICIES.md`; queue order in `BACKLOG.md`.

> **Canonical ledger rule:** regardless of the reviewed worktree, read and
> append through `/Users/jerryyu/Projects/shengji/HANDOFF_ACTIVE.md` and
> `/Users/jerryyu/Projects/shengji/HANDOFF_REVIEW.md`. A branch-local copy is
> never review authority. Raw markers start at column 1 and occur exactly once.

## Immediate state

The current blocker is one independent score-free REPORT-controller review:

- `TEACHER_STAGE_C_V11_FREE_FRESH_REPORT_RESULT_V1_REVIEW` terminalized the
  protected-anchor policy as **SELECT_NONE**. It triggered 171/480 states but
  lost to candidate zero (paired mean `-0.00822754`, LCB `-0.01894357`). Do
  not retry a threshold, reuse REPORT, compose, screen, promote or deploy it.
- `TEACHER_STAGE_C_EXPANDED_LABEL_RESULT_V1_REVIEW` independently passed the
  5,504-label terminal result: 16/16 shards, zero refusals, exact 13,136,320
  candidate worlds, aggregate `3deb3a81…f6ca` and receipt `48a64759…8efe`.
- Claude independently passed the terminal 96-cell result. DESIGN/CALIB
  selected eight epoch-32 all-pairs bury rankers: 8/8 positive seeds, median
  candidate-zero improvement `+0.016418`. The direct candidate-zero loss did
  not win, so expanded coverage—not the new objective—is the supported cause.
- Codex consumed the single score-free freeze authority. Draft PR #32 exact
  `50e1464` froze and independently rebuilt packet `5ce892db…25f0`: the exact
  eight-model ensemble, 32 untouched bury states, eight four-state shards and
  a 262,848 candidate-world ceiling. Predictions, labels and utility remain
  zero. The raw controller review is the sole current REPORT gate.

Air separately preserves the reviewed S4 point-banking replication at exact
`fb6ec1a`, receipt `fc6d54e7…1077`. Eight workers remain healthy; consult the
run ledger for the latest score-free heartbeat rather than copying volatile
counts into this mailbox. Never inspect
interim utility, stop/restart a healthy shard, retry, extend or tune the run.

## Current truth and next legal action

| area | current truth | next legal action |
|---|---|---|
| Production | Release 17 runs compiled, confirmed `mc-s0-report-lcb`. PR #11's independently reviewed Xray kitty-bury view merged at `970cacd`. | Monitor only; T4 authorizes no production policy change. |
| S4 | Original whole-game screen PASS is preserved. Independent fixed replication is live on Air: 2,048 treatment/champion clusters plus 256 exact-null sentinels. | On terminal publication, run the pinned verifier and request an independent terminal-result review. |
| Stage-C original generation | Capture/state set and 2,048 iid-v2 labels passed. The first 1,536-state, eight-seed model generation selected none. Its protected-anchor fresh REPORT also selected none. | Closed without composition. Use the negative to test scale versus objective alignment; never reopen either spent REPORT. |
| Expanded labels | **Terminal COMPLETE / externally passed:** 5,504 new labels plus 1,536 retained labels yield 7,040 DESIGN/CALIB examples. Third REPORT is sealed at 512 states. | Closed as a data asset; its one freeze authority is consumed. It grants no training or REPORT access. |
| Expanded training | **Terminal external PASS:** all 96 cells and 576 checkpoints replayed. Selected epoch-32 all-pairs bury ranking, 8/8 positive seeds; direct loss did not win. | Closed as a CALIB capability result. Its one downstream packet-freeze authority is consumed. |
| REPORT/composition | **Packet frozen / external review open:** PR #32 packet `5ce892db…25f0` binds the selected ensemble to 32 untouched bury rows. Zero predictions, labels, utility, admission or execution exists. | Claude posts raw `TEACHER_STAGE_C_EXPANDED_FRESH_REPORT_CONTROLLER_V1_REVIEW`. Only PASS opens REPORT once; compose only a REPORT passer inside report-LCB with fallback and same-work null. |
| S6 shuai-pai | Draft PR #19 `2605b04` guarantees at least one bounded public lead-only shuai candidate whenever legal, including KESP and late trump-only witnesses. Twelve focused/59 broader tests and a 200-deal coverage audit pass. No screen exists. | Obtain external source-semantics review, then design an equal-work state screen. Do not consume T4 compute or merge an unused source. |
| Repository hygiene | PR #11 merged; status-only PRs #10/#12/#21/#25 closed; 16 remote branches, eight merged/superseded local branches and 15 clean worktrees removed; one stale missing-worktree record pruned. Nine source-required markers lost by `d5348da` were recovered byte-exact and regression-protected. Draft PR #31 proves and removes only unreferenced `segbatch.py`; source-pinned candidates remain untouched. | Review/merge PR #30, retarget/review #31, then consolidate the Stage-C stack on current `main` after terminal evidence. Close/delete ancestors only after ignored evidence is tagged or archived. |

## Review boundaries

1. **Expanded labels:** terminal 5,504/5,504 completion passed external replay;
   its one packet-freeze authority is consumed and grants nothing further.
2. **Expanded training packet:** externally passed and consumed exactly once;
   the 96-cell execution is terminal and never retried.
3. **Training result:** externally passed and consumed exactly once for the
   score-free packet freeze; it grants no REPORT execution.
4. **REPORT:** packet review is open. Only its raw PASS permits one untouched
   look. A non-passer closes without threshold tuning or composition.
5. **Whole-game screen:** only a REPORT passer may be composed and screened.
   The active `/goal` stops before confirmation, promotion or deployment.

## Safety boundary

- Preserve all consumed capture, capacity, label, training and REPORT slots.
  Never retry or pool a terminal no-use generation.
- H0 is terminal incomplete at 555/557; no human-derived proposal rule was
  admitted and partial utilities remain unread.
- Label v1's realized-world deduplication was posterior-changing. All current
  folds use domain-separated iid draws with replacement.
- Do not open REPORT during labeling, controller review, training or
  DESIGN/CALIB selection.
- Do not launch S4 confirmation, S6, S5 or an unreviewed Teacher stage merely
  to occupy idle compute.
- Simplification may consolidate duplicated plumbing, but it may not weaken
  one-shot admission, identity binding, replay, refusal or evidence isolation.
