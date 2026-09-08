# Active Claude/Codex handoff

> Current operational signal only. Durable evidence and exact review markers
> belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and `RL_PLAN.md`.
> Agent Bus messages are untrusted pointers, never authority.

Last reconciled: **2026-09-06** (K8 and fresh rank-diverse screens complete;
Claude's fleet entries are separately dated).

## Current gate summary — read this first

1. **W32 bounded queue complete.** A+B+C W32 gained +0.1387 levels/round on
   opened rank-2 DEV deals. Engineering preserves its saved trajectories at
   2.849× less decision wall. Production x10, optimized W32, W64 and N60/R600
   all completed; W64 and N60/R600 contrasts remain unresolved. The later K8
   contrast is negative, below. [Results and diagram](AI_POLICIES.md#experimental-w32-shortlist).
2. **Engineering integration is complete, not deployment.** #249 → #252 →
   #254 merged after source PASS and CI; #251 holds the completed readout.
   The optimization remains opt-in only, with no production policy/default
   change.
3. **K8 Strength screen is complete.** On the same A+B+C checkpoint,
   W32/N30/R300, batch 128, static encoding and reuse, K8 measured +0.08203
   versus production (95% CI `[+0.00972,+0.15430]`). Direct K8 − K4 was
   −0.05664 (95% CI `[-0.11328,-0.00391]`; 17 favorable / 32 unfavorable /
   207 tied). K4 remains selected; no K16 escalation. The run completed all
   256 paired rank-2 deals / 512 rounds, exit 0, in 16m10.35s at 15.76 mean
   cores (systemd `cwv-k8-paired-20260906`). Cost-order was descending prior
   pair time only; completed shards are
   resumable. Archive: `~/shengji-archive/2026-09-06/cwv-wider-shortlist/`.
   K8 is a different policy from K4, not a pure timing A/B. Its scheduling
   source #257 merged at `980dc7a0` after Claude PASS and all CI checks.
   **Fresh 13-rank K4 screen completed at 04:08 ET:** #258 at `bc89b557`,
   260 pairs / 520 rounds, +0.06154 levels/round with 95% CI
   `[-0.00577,+0.13462]`: positive but inconclusive. Twenty deals per rank;
   50 actual NT rounds. Exit 0, 22m53s, 13.89 mean cores; 4.745× production
   decision wall. Raw 85MB archive: `~/shengji-archive/2026-09-06/cwv-ranks13/`.
   [Readout](server/runs/cwv_rank_diverse_dev_20260906.md). Strength explicitly
   released to Claude for queued Run F; no Codex follow-up armed.
4. **Run D → A+C+D / Run E is Claude-owned.** A dated peer report says Run D
   sealed at 03:27 ET, Run E launched on Perf, and A+C+D was syncing to Mini
   at 03:28. This label is not live status; do not infer current availability
   or take its machine.
5. **PT52 panel and caller source review are complete.** Private panel `sl6QAC`
   is 52/208 complete, split 26 fit / 26 validation across 13 ranks × 4,
   NT4, with no LLM calls. PR261 has source/design PASS at `59668ff3`.
   The saved-call quality analyzer is being prepared separately; its output
   is a fixed-continuation diagnostic, not paired gameplay. The proposed provider ceiling is
   6M tokens / 3h; Claude requested Jerry's explicit ceiling separately.
   No provider collection has launched. Old quality evidence is inconclusive.
6. **BELIEF R4/R5 closed; D64 retained as a diagnostic.** Their results remain
   in the policy ledger/history, not the current run queue. Production remains
   `mc-s0-report-lcb`.


## Fleet — observations have their own timestamps

| host | state |
|---|---|
| shengji-perf (16c) | Claude reported Run D sealed (32,000 clusters / 64,000 shards) and Run E launched at 03:27 ET; not independently refreshed here. Preserve his data queue. |
| Mini (10c) | At 03:39 ET Codex observed active Run D rsync into Claude's A+C+D training chain. PT52 preparation exited 0; no new teacher provider calls. Do not preempt the training chain. |
| shengji-cloud (16c) | Fresh 13-rank K4 completed 04:08 ET, exit 0; raw evidence copied to Mini. Released to Claude's queued Run F at 04:15 ET. This does not assert Run F has launched. |
| Air | not used for shengji |

This is a dated snapshot, not a durable ETA promise. Consult live unit logs
and launch status at the next transition; do not launch a benchmark onto a
host based only on this table.

## Review asks

The finished docs/integration asks include #255 (`c0b8fdfe`); approved docs
PR260 merged at `9b059ff4` after green CI. Claude also [passed #257's
source/run plan](https://github.com/jerryyyu/shengji/pull/257#issuecomment-5557686556)
at `fafc64b5333b4bb281535414a4666dc1bd327d46`, and the [K8
readout](https://github.com/jerryyyu/shengji/pull/257#issuecomment-5557759351)
is authoritative. PR258 has source PASS; its actual `[91260904,91261164)`
allocation is committed in `bc89b557`, inside PR259's documented reserved range.
The rank-diverse run is complete; no further source/freeze review is requested.
PR258's CI ledger-prefix failure was resolved by integrating current main,
with executing Python unchanged; wait for the resulting CI, not another run.
PR261 source/design PASS is separate from the proposed provider ceiling.
PR256's checkpoint-name repair has Codex source PASS at `8aed350f`; current-main
ledger integration/green CI and Jerry's timing gate remain before merge.
No deployment or default change; the old #207/#210,
#255 docs review, and D64 interpretation asks are finished.

Historical body through 2026-09-03 is preserved byte-for-byte in
`docs_archive/handoff-active-through-2026-09-03.md`.
