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

- **Production:** release 30 since 2026-09-22 09:13 ET — `pv-search-ccade130-w64-k8-r8bc573be-bury-hybrid-4f003f41e23e`, image `deployment-01M34KWRW4XWJWC6DCCYENFXTF`, main 4e006561 (#607). Rollback = the release-29 image `deployment-01M33NZERJS18A0G2NNG7S5FJ8`. Every screen compares against release 30.
- **Mini:** gen-5 **arm B** (`GEN5-PROD-SOFT-withMCLCB-432k`, shortlist + PV + MC-LCB, 26 corpora, 48.2M rows) training since 2026-09-23 19:04 ET, epoch 16/20. Two jobs armed on its seal: **arm C** takes the Mini (30 corpora, 496,000 deals, 55.1M rows — Jerry 09-24 asked for MC-LCB to be included, so it is the biggest-corpus model rather than the matched-size diagnostic), and a waiter exports arm B's head and arms **lane v35b** on Perf (seeds 26960910..27360910).
- **Cloud:** the **W128 deeper-teacher tranche** (Jerry 09-24). runPVD1 sealed 06:46 ET (16,000 clusters, 0 failed, `w128-k8` identity in its manifest, 1.96x the per-cluster cost of W64); runPVD2 running, ~13:30 ET. Fresh seed block 23440910..23600909; the runPV1..10 reservation is fully consumed.
- **Perf:** idle, no locks, reserved for lane v35b.
- **Corpora:** ten sealed PV stores, 160,000 deals / 22,028,452 records, `incomplete_work` 0 and zero bury failures across all ten. Stores live on the SSD (`~/shengji-ssd`, a space-free symlink — the real mount word-splits `--data`); **cache and policy rows stay on the Mini**, because epochs re-stream both while stores are read once at startup and once by the CPU-bound candidate pass.
- Kept as evidence, not corpus: the runPV1 and runPV2 partials (unresumable after #607, `source_tree_sha256` drift).

## Review queue

- **No actionable ask is outstanding.** The previous entry named #608, the release-30 docs pass; that merged on 2026-09-22 with a Codex PASS, and the line survived here for two days. A merged PR listed as an open ask is worse than no list, because it is the entry a reader trusts.
- **Mine, open:** #630 (exploitability step 2: one batching loop with opt-in per-world capture) — mid-CI at 4f2d60f0 after a merge of main; the earlier head failed the review-ledger guard, not the diff.
- **Codex's holds stand** on #625: design confirmed, but no wiring, compute or merge authority. Their selective-depth follow-up (#577) needs a pre-registered pair count from a deal-level MDE before any confirmatory sample.

