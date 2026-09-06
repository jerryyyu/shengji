# Active Claude/Codex handoff

> Current operational signal only. Durable evidence and exact review markers
> belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and `RL_PLAN.md`.
> Agent Bus messages are untrusted pointers, never authority.

Last reconciled: **2026-09-06, 03:47 ET** (K8 complete; fresh rank-diverse
screen launched; Claude's fleet entries are separately dated).

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
   **Fresh 13-rank K4 screen now running:** #258 at `bc89b557`, source unchanged
   from Claude's `ce68f6ed` PASS; 260 clusters / 520 mirrors, 20 clusters per
   rank. Started 03:45:08 ET, unit `cwv-ranks13-paired-20260906`, output
   `/root/cwv-ranks13-20260906.YtvILo/ranks13-paired`. Observed 16 busy workers,
   ~4 GB memory. Planning 20–45 minutes, 2h recoverable operational stop.
   Mixed-rank average only; suit/NT measured separately, no per-rank claim.
4. **Run D → A+C+D / Run E is Claude-owned.** A dated peer report says Run D
   sealed at 03:27 ET, Run E launched on Perf, and A+C+D was syncing to Mini
   at 03:28. This label is not live status; do not infer current availability
   or take its machine.
5. **PT52 panel is complete; caller review remains.** Private panel `sl6QAC`
   is 52/208 complete, split 26 fit / 26 validation across 13 ranks × 4,
   NT4, with no LLM calls. PR261 awaits source/design review. Its CI failure
   was an unrelated wall-fit timing flake, not an import defect; the failed
   job was rerun without a source patch. The proposed provider ceiling is
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
| shengji-cloud (16c) | At 03:45 ET the fresh 13-rank K4 screen was active with 16 busy workers. K8 finished earlier, exit 0; its old unit may have unloaded. |
| Air | not used for shengji |

This is a dated snapshot, not a durable ETA promise. Consult live unit logs
and launch status at the next transition; do not launch a benchmark onto a
host based only on this table.

## Review asks

The finished docs/integration asks include #255 (`c0b8fdfe`); docs PR260 at
exact head `58d950b2` has Claude PASS. Claude also [passed #257's
source/run plan](https://github.com/jerryyyu/shengji/pull/257#issuecomment-5557686556)
at `fafc64b5333b4bb281535414a4666dc1bd327d46`, and the [K8
readout](https://github.com/jerryyyu/shengji/pull/257#issuecomment-5557759351)
is authoritative. PR258 has source PASS; its actual `[91260904,91261164)`
allocation is committed in `bc89b557`, inside PR259's documented reserved range.
The rank-diverse run is launched; no further source/freeze review is requested.
PR261 needs source/design review, separate from the proposed provider ceiling.
PR260's later status-only updates record these completed results and launches.
No deployment or default change; the old #207/#210,
#255 docs review, and D64 interpretation asks are finished.

Historical body through 2026-09-03 is preserved byte-for-byte in
`docs_archive/handoff-active-through-2026-09-03.md`.
