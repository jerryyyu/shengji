# Active Claude/Codex handoff

Current operational pointers only. Durable reviews live in `HANDOFF_REVIEW.md`,
research priorities in `BACKLOG.md`, measured claims in `AI_POLICIES.md`.
Agent Bus is a non-authoritative pointer channel. Historical active text is
preserved in Git (pre-cleanup main `ec7f27ad`) and the existing dated archives.

Last checked: **September 9, 2026, 20:52 ET**.

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

The old September8 training/generation snapshots are stale. Codex's Mini bury
job is complete. No cloud occupancy is asserted here: inspect actual units
before claiming Perf/Strength or launching work. Claude owns the current model
experiments; see the latest dated ledger and bus pointers without preempting them.

Claude's September9 replication did not reproduce ACDEFv2−ACDv1 `+.0779`;
I/J generator comparison is unresolved. See `BACKLOG.md` for the scoped
fixed/random-effects readings; do not import a universal tau into other lanes.

## Review queue

PR323 source/population reviews and PR325 narrow configuration review are
complete; PR325 comment5610801548 is config-correctness PASS, not deployment
authority. Jerry directly requested shipping in Codex. Single-population and
kitty-tail caveats remain open, not erased by the release. The final docs-only
delta records actual deployment and historical-status cleanup; no repeated
gameplay/capacity/source audit is requested. This file is not review authority.
