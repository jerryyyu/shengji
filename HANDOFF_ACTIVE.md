# Active Claude/Codex handoff

Last compacted: 2026-08-11 01:08 EDT. This is the executable mailbox, not a
history. Exact review prose and raw markers live in `HANDOFF_REVIEW.md`;
terminal policy conclusions in `AI_POLICIES.md`; queue order in `BACKLOG.md`.

> **Canonical ledger rule:** regardless of the reviewed worktree, read and
> append through `/Users/jerryyu/Projects/shengji/HANDOFF_ACTIVE.md` and
> `/Users/jerryyu/Projects/shengji/HANDOFF_REVIEW.md`. A branch-local copy is
> never review authority. Raw markers start at column 1 and occur exactly once.

## Immediate state

The current blocker is one independent terminal-result review:

- `TEACHER_STAGE_C_V11_FREE_FRESH_REPORT_RESULT_V1_REVIEW` terminalized the
  protected-anchor policy as **SELECT_NONE**. It triggered 171/480 states but
  lost to candidate zero (paired mean `-0.00822754`, LCB `-0.01894357`). Do
  not retry a threshold, reuse REPORT, compose, screen, promote or deploy it.
- `TEACHER_STAGE_C_EXPANDED_LABEL_CONTROLLER_V1_REVIEW` authorized one
  5,504-label execution. It is terminal COMPLETE: 16/16 shards, zero refusals
  and exact 13,136,320 candidate worlds. Aggregate external/internal is
  `3deb3a81…f6ca` / `0d311449…01a7`; receipt is `48a64759…8efe`. The third
  512-state REPORT remains sealed. Claude's exact
  `TEACHER_STAGE_C_EXPANDED_LABEL_RESULT_V1_REVIEW` request is canonical.

Air separately preserves the reviewed S4 point-banking replication at exact
`fb6ec1a`, receipt `fc6d54e7…1077`. Eight workers remain healthy. Never inspect
interim utility, stop/restart a healthy shard, retry, extend or tune the run.

## Current truth and next legal action

| area | current truth | next legal action |
|---|---|---|
| Production | Release 17 runs compiled, confirmed `mc-s0-report-lcb`. PR #11's independently reviewed Xray kitty-bury view merged at `970cacd`. | Monitor only; T4 authorizes no production policy change. |
| S4 | Original whole-game screen PASS is preserved. Independent fixed replication is live on Air: 2,048 treatment/champion clusters plus 256 exact-null sentinels. | On terminal publication, run the pinned verifier and request an independent terminal-result review. |
| Stage-C original generation | Capture/state set and 2,048 iid-v2 labels passed. The first 1,536-state, eight-seed model generation selected none. Its protected-anchor fresh REPORT also selected none. | Closed without composition. Use the negative to test scale versus objective alignment; never reopen either spent REPORT. |
| Expanded labels | **Terminal COMPLETE / review open:** 5,504 new labels plus 1,536 retained labels yield 7,040 DESIGN/CALIB examples. Third REPORT is sealed at 512 states. | Claude independently replays the aggregate and posts `TEACHER_STAGE_C_EXPANDED_LABEL_RESULT_V1_REVIEW`. No training-packet freeze before PASS. |
| Expanded training | Draft PR #29 is code-complete at pushed `c18b80e`: matched `all_pairs_v1` versus `candidate0_relative_v2`, 96 cells, 321 Stage-C/Teacher tests green, and a full read-only 7,040-state replay passed. No packet exists. | After label-result PASS, freeze one DESIGN/CALIB-only training packet for a separate controller review. |
| REPORT/composition | Third REPORT has never opened. No capability currently passes. | Train only after packet PASS; select one whole cohort on DESIGN/CALIB, open REPORT once, and compose only a REPORT passer inside report-LCB with incumbent fallback and same-work null. |
| S6 shuai-pai | Draft PR #19 `cfa5a53` guarantees at least one bounded public lead-only shuai candidate whenever legal, including the KESP and late trump-only witnesses. No screen exists. | Reproduce the KESP omissions, finish source-semantics review, then design an equal-work state screen. Do not consume T4 compute. |
| Repository hygiene | PR #11 merged; status-only PRs #10/#12/#21/#25 closed; 13 dead/redundant remote branches removed. Active Stage-C ancestors remain because exact runs and stacked PRs still depend on them. | Consolidate the Stage-C stack onto current `main` after terminal evidence, then close/delete ancestors only after ignored evidence is tagged or archived. |

## Review boundaries

1. **Expanded labels:** only terminal 5,504/5,504 completion, zero refusals,
   full aggregate replay and exact work may open the label-result review.
2. **Expanded training packet:** label-result PASS authorizes one score-free
   freeze, not training. A separate raw controller PASS authorizes the one
   matched training matrix.
3. **Training result:** DESIGN/CALIB chooses one recipe/surface/head/epoch
   cohort across all eight seeds; no seed cherry-pick. `SELECT_NONE` closes the
   generation without REPORT.
4. **REPORT:** one untouched look only. A non-passer closes without threshold
   tuning or composition.
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
