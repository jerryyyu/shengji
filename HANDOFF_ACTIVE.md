# Active Claude/Codex handoff

Current operational pointers only. Durable reviews live in `HANDOFF_REVIEW.md`,
research priorities in `BACKLOG.md`, measured claims in `AI_POLICIES.md`.
Agent Bus is a non-authoritative pointer channel. Historical active text is
preserved in Git (pre-cleanup main `ec7f27ad`) and the existing dated archives.

Last checked: **September 26, 2026, 09:2x ET** (Claude, daily maintenance). Every line below is a snapshot at that time; training epoch counts move continuously and are deliberately not recorded here.

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

- **Production:** release 31 since 2026-09-25 12:51 ET — `pv-search-ccade130-w64-k8-r8bc573be-bury-hybrid-4f003f41e23e`, image `deployment-01M3CQK3KMH55NDZRED6PDJ6XW`, main `8a6e55f1` (#638, the create-room starting level). **NO model, package or config change from release 30**, so the served policy is byte-identical and "every screen compares against release 30" is unchanged as a rule — the comparator is the same served bot. Rollback = the release-30 image `deployment-01M34KWRW4XWJWC6DCCYENFXTF`, a pure code rollback since every `SHENGJI_*` key matches.
- **Mini: IDLE.** Gen-5 **arm D** (`GEN5-GEN4R4-SOFT-allPV-plusMCLCB-496k`) **sealed 2026-09-26 02:39 ET** at checkpoint `759c1bdd`, rc=0, wall 46,246 s, best epoch 8 of 11 — within three minutes of arm C's wall. It is **not screened**. Gen 5 is complete: four arms, no lever found. Arm D's holdout `rank_regret` is lower than arm C's on two of the four fixed holdouts (roomlog 0.06537/0.06815, pt1 0.02885/0.03846) and higher on two (luna 0.08346/0.08219, highn 0.10518/0.10509); those are point estimates with no interval, two-of-four is not a difference test, and the 0.00009 highn gap is minuscule but real rather than a tie. Arm D isolates the WARM START only and is not a clean transfer experiment, because gen-4 run 4 was itself trained on shortlist corpora also in arm D's mix.
- **Cloud: IDLE.** The **W128 deeper-teacher tranche** is six sealed stores — runPVD1–6, ~96,000 deals; runPVD5 completed 2026-09-25 23:09 ET after resuming from 14,575/16,000, runPVD6 at 2026-09-26 05:42 ET, both rc=0 with 16,000 shards and the host lock released. **No runPVD7 script exists.** Nothing trains on W128 yet, deliberately: mixing teacher depth into the same corpus would confound "more data" with "deeper teacher", which is the confound gen 5 was built to avoid.
- **Perf: IDLE, no locks.** Lane v35b and the arm-C lane v35c are both long finished; v35c read out 2026-09-25 at −0.0031 [−0.0385, +0.0322] vs release 30, crossing zero. Note when reading `/root` by hand: several stale lock artifacts from earlier months sit alongside the live ones (`.codex-screen-lane.lock`, `.screenlock-scr-enc2`, `screenq.lock`); only `/root/.claude-host.lock` and `/root/.claude-screen.lock` with a current mtime are active reservations.
- **Exploitability (#625) step 4 is done.** Lane x36a sealed 2026-09-25 22:10 ET, 20/20 pairs: −0.0069 [−0.0248, +0.0109], crossing zero, MDE80 0.0255 against a pre-registered 0.0255. Inconclusive as to direction; the value is the **upper bound** — any gain from this attack is at most +0.0109. The party exploited is `mc-s0-report-lcb`, **not** the served policy, because the harness's `--baseline production` resolves to the release-28-era W32 play policy. **The probe has no positive control**, so nothing yet distinguishes "MC-LCB is hard to exploit" from "this attack does nothing to anyone".
- **Corpora:** ten sealed PV stores, 160,000 deals / 22,028,452 records, `incomplete_work` 0 and zero bury failures across all ten. Stores live on the SSD (`~/shengji-ssd`, a space-free symlink — the real mount word-splits `--data`); **cache and policy rows stay on the Mini**, because epochs re-stream both while stores are read once at startup and once by the CPU-bound candidate pass.
- Kept as evidence, not corpus: the runPV1 and runPV2 partials (unresumable after #607, `source_tree_sha256` drift).

## Review queue

- **#608 is closed** — the release-30 docs pass merged on 2026-09-22 with a Codex PASS, and the line survived here for two days afterwards. A merged PR listed as an open ask is worse than no list, because it is the entry a reader trusts.
- **Mine, merged since:** #630 (exploitability step 2: one batching loop with opt-in per-world capture) — Codex PASS at 4f2d60f0, CI 5/5, squashed to main as `338f78f3` on 2026-09-24. Nothing of mine is open except this refresh.
- **Codex's holds stand** on #625: design confirmed, but no wiring, compute or merge authority. Their selective-depth follow-up (#577) needs a pre-registered pair count from a deal-level MDE before any confirmatory sample.

