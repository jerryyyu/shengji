# Active Claude/Codex handoff

Current operational pointers only. Durable reviews live in `HANDOFF_REVIEW.md`,
research priorities in `BACKLOG.md`, measured claims in `AI_POLICIES.md`.
Agent Bus is a non-authoritative pointer channel. Historical active text is
preserved in Git (pre-cleanup main `ec7f27ad`) and the existing dated archives.

Last checked: **September 22, 2026, 09:2x ET** (Claude, daily maintenance).

## Shipped — Codex

- Jerry requested shipping hybrid bury and a documentation sweep. PR #323
  merged at `ec7f27ad`; unchanged W32 play uses compact `fd6bb411`, source
  ACDEF v2 `3cd27716`.
- Live release snapshot: Fly release22, W32 play / hybrid bury,
  machine `48e7e35a9597e8`, one shared CPU,512MiB, existing volume, zero rooms.
  Recheck `/healthz` before restart; this is not a standing empty-room claim.
- Deployed policy:
  `mc-shortlist-fd6bb411-w32-r55d379a3-bury-hybrid-c93a9877ae6a`.
  Baseline32/32/32,2-second cooperative search budget, legal heuristic fallback.
  Registration alone does not activate it; `SHENGJI_BOT` selects the exact name.
- Focused config/serving/boundary/registry tests17/17; native no-Torch actual
  consumer2-second probe11/11. The earlier Linux1CPU/512MiB probe11/11 passed.
  PR325 CI passed. Image `b5dc327f…1030c82d` deployed; live health and literal
  model/encoder SHA checks passed. Isolated functional bury0.803s, legal8,
  unchanged playRNG, noTorch, nofallback, no synthetic human-log game.
- Release evidence: `~/shengji-archive/2026-09-09/bury-shipping.VIDnz5/`.
  Bury-only rollback restores base W32 and removes both BURY settings together;
  preserve model/log volume. See `DEPLOY.md` for image/occupancy details.

## Completed research, not a live queue

- Bury fixed512 scaling and fresh1976 all-rank confirmation completed.
  Hybrid−heuristic utility `+.03644 [.01164,.06024]`, wins `+1.62pp`;
  hybrid−MC unresolved. Kitty80+ events4 versus0 heuristic. No queued bury
  compute, no full-round throughput gain. [Final report](docs_archive/value-guided-bury-dev-2026-09-08.md).
- PT-Luna52-deal paired gameplay and native harvest are merged. Efficiency
  improved but equal quality was not established; opened validation stays out
  of fitting and fresh confirmation. No new provider run queued by Codex.
- BELIEF R4/R5 retired;18 exact source heads archived before PR closure.
  The original test is spent. D64 remains a diagnostic, not a restart.
- Earlier shortlist K/W/depth/allocation experiments remain dated evidence,
  not unfinished implementation or approval gates.

## Fleet and coordination

- **Production:** release 30 since 2026-09-22 09:13 ET — `pv-search-ccade130-w64-k8-r8bc573be-bury-hybrid-4f003f41e23e`, image `deployment-01M34KWRW4XWJWC6DCCYENFXTF`, main `4e006561`; release 29 (00:29 ET) is the image rollback. Every screen from here compares against release 30 (Jerry).
- **Perf:** lane v34r5 (run 4's head served vs release 30 as served), tree `/root/claude-main-13` at 4e006561, OUT `/root/vol-screen-claude-v34r5-r30-20260922`, seeds 23960910..24360910; readout ~11:45 ET. 28 GB free.
- **Cloud:** Codex's depth screen (`codex-depth-screen-20260922` service, 260 × 3 arms, ~12:45 ET). The PV regenerations (runPV1r/runPV2r, tree at 4e006561) arm after it ends.
- **Mini:** gen-4 run 3 (GEN4-G1-SOFT-336k) training, epoch 5/20, seal ~03:30 ET 09-23; run 2 armed behind it. Memory tight while training.
- Stopped and kept as evidence: runPV1 (cloud) and runPV2 (Perf) partial stores (unresumable after #607); the three release-29-tree windows of the first v34r5 launch.

## Review queue

- **One actionable ask:** #608 — docs pass for release 30 (DEPLOY, README, AI_POLICIES, RL_PLAN, BACKLOG, this file) at its current head; Codex PASS + CI 5/5 to merge.
- Codex's held launchers: #599 at 6b49515b and #601 at 06999b0d PASSed 09-22 (the hold-release commit should update the receipt's reservation/authorization strings).
