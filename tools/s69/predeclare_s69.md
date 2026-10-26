# Predeclaration: s69, the S61 red-team design re-run against R48 (board #1075 row S69), on shengji-cloud

Written 2026-10-26 (UTC) by Claude, before any s69 lane deal is played and before any RELEASE. The only deals played so far are the local
smoke (4 deals, 311970000–311970003) and the host rehearsal (36 deals, 311960000–311960035), both throwaway windows. The reader
(`s69_read.py`) evaluates the read exactly as written here.

**Revision r2** (2026-10-26, still before any lane deal): the producer runs with `--history`, so every row keeps `buried`, `history`
and `failed_detail`, and S69's top cells can feed same-root replay fixtures. S61's extraction was refused because its producer ran
without it. The reader gains a history gate that refuses a row without these fields or with fields inconsistent with the trace. The
launcher is `claude_s69_r2_cloud.sh`, the reader `s69_read_r2.py`, the reservation `s69_r2.json`. The read, arms, seeds and thresholds
are r1's. The r3 host re-rehearsal (12 deals) measured the cost of `--history`; r1's files are in `superseded-r1/`.

**Why.** Board row S69: where does R48 lose now? S61 ran against release 46, whose top loss cells R48 has since absorbed (S58, dtrx, lgf,
the sc8 path). This lane re-runs the S61 design against R48 to find the gap again. Tier i DEV under `RL_PLAN.md` "Operating modes".

**Authority.** Jerry 2026-10-26 in Claude's session: "The combo and red team sound good to test". That covers tests only, with no deploy.
The RELEASE still needs Codex's non-author PASS of this packet.

## The predeclared read (verbatim, as briefed)

> 600 seat-swapped pairs head-to-head; report head-to-head margin (levels/round) with deal-cluster 95% CI; loss attribution by
> first-divergence cell (decision class lead/follow/bury/declare × trick band × rank group) with each cell's contribution and CI; list
> top-3 cells. Not a strength claim for any servable candidate; exploiter is not servable. Validity: zero play/belief fallbacks both sides
> (or the S61 ceilings, same on both arms), worlds delivered as configured. Comparison lines vs S61 must report difference with its
> interval and the caveat "independent runs, not a paired test".

Of the two validity options above, this lane takes **zero play and zero belief fallbacks on both sides**. The same mapping applies to
both arms: bury fallbacks ≤ 1% of the side's buries and declare abandons ≤ 1% of its declare evaluations. That is s65dev's mapping for
R48 against R48.

## The arms (existing knobs only; no code change)

| | defender seats | exploiter seats |
|---|---|---|
| bot | R48 exactly as served: fly.toml `SHENGJI_BOT` at origin/main `d33bfd70` (sha `ff64b52f…`; its `SHENGJI_PV_*` / `SHENGJI_BOT` lines byte-identical to `0c1e9965`'s), S58 `s58-e6-42444515` at its stored T 1.0129 | R48 + the nine `--exploiter-env` overrides below (the M27 expert budget) |
| name | `pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-rc252e656-bury-hybrid-bwv-cd6dd3d2b02a` | `pv-search-491ee4bf-w256-k32-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-ed8-els9000-edn200000000-xf8-xfcompactlevel-r9779eb5a-bury-hybrid-bwv-80b4500430de` |

The exploiter's overrides are the M27 expert config, confirmed from M27's packet (`fl-pilot/h1a/ask_h1a.md`: "256 belief worlds, K 32,
exact 8/8, 9 s / 2e8, no lgfd, 60 s cap"):

| knob | defender (served) | exploiter |
|---|---|---|
| `SHENGJI_PV_WORLDS` / `_CANDIDATES` | 64 / 8 | 256 / 32 |
| `_EXACT_DEEP_CARDS` / `_EXACT_FOLLOW_MAX_CARDS` | 7 / 7 | 8 / 8 |
| `_EXACT_LEAD_MAX_SECONDS` | 2.25 | 9.0 |
| `_EXACT_DEEP_MAX_NODES` / `_EXACT_FOLLOW_MAX_NODES` | 5e7 / 5e7 | 2e8 / 2e8 |
| `_SERVING_BUDGET_SECONDS` | 3 | 60 (M27's 60 s cap) |
| `_LEAF_GREEDY_DEADLINE` | 2 (lgfd 2000) | removed (an empty value: no lgfd; `leaf_greedy_deadline_ms` 0) |

`check_names` derives both names on the host through the harness's own `variant_factory`. It asserts that the config diff is exactly these
nine fields. It also asserts, on both sides: the three fly.toml latency switches (`encode_prefix_cache`, `leaf_greedy_stream`,
`encode_batch_fast`), the same S58 package and temperature, the bury budget of 2 s, the hybrid bury arm, and the r2 plan head.

**Differences from M27's expert, stated.**
- M27 set its 60 s cap on the built bot. Here it is the env budget. The budget is in the recipe digest, so the name differs from M27's
  (`…rf46b9754…63b7cb149669`) in the digest only.
- M27 lifted the belief preparation cap to ∞ process-wide for every bot. Here both sides keep the served 0.25 s cap. A breach is a belief
  fallback, so V counts it.
- The exploiter's declare and bury knobs are R48's, as in S61 r2, so the first divergences land in play.

## The duel

| | |
|---|---|
| harness | `exploit_duel_s61.py` (`b15d292f…`, the reviewed resumable S61 producer, verbatim; the same bytes as s63dev–s66dev), `hypotheses.py` (`4365a15d…`), `--arm identity`, **`--history`** (r2) |
| pairing | Every deal is played twice with the teams swapped. The per-(deal, seat) seeds do not depend on the arm or the mirror. |
| tree | `/root/claude-main-56` = origin/main `d33bfd70`, a fresh cloud build (`claude_build_main56_cloud.sh`, BUILD_RC=0). Its extensions are pinned in the launcher (`e3b22690` / `325d607f` / `776988da`). |
| deals | **600**, seeds `311060910 … 311061509`, the r2 rank-mixed plan per deal (index % 10 ∈ {0,3,5,8}: first round at rank 2; otherwise a fixed banker at rank `RANKS13[index % 13]`), 12 workers |
| host | shengji-cloud (16 vCPU), python `/root/gen-hybrid/server/.venv/bin/python` (3.14), the shared mkdir host lock, no S17 handshake, MemAvailable ≥ 12 GiB, hard stop 28,800 s (backstop 28,810 s) |

## The read (the reader evaluates exactly this)

- **Binding (refuses), first.**
  - `reader_lib.bind_inputs`: the root, status and reservation are the reserved dispatch paths, and the reservation names this lane, the
    launcher sha (= the RELEASE token), the status and the root.
  - The status has exactly one terminal line, `<stamp> s69 DEV output sealed; rc/status only (strength qualification is reader-owned);
    LANE DONE`, and no ABORT: or REFUSING: line (NO_TAIL).
  - Before the terminal line come exactly one DEV start line (the launcher's exact text) and one `DEV END rc=0` line.
  - `<root>/duel.jsonl`'s sha256 equals its line in `<root>/SHA256SUMS`.
- **Integrity (refuses).** s61dev's checks, unchanged:
  - arm identity, no fired override, the two pinned names, 600 × 2 rows on the r2 plan;
  - the 19-field dhist row schema on both sides, with exact_deep_cards 8 on the exploiter and 7 on the defender;
  - the reconciliations, no defender 8-card exact stage, and at least one complete exploiter 8-card lead and follow;
  - declare / bury shapes at 64 / 32 / K ≤ 64 on both sides;
  - the decision trace (`trace_gate`), and the first divergence differing in cards only;
  - (r2) the play history (`history_gate`): `buried` equals the trace's bury; one `history` entry per trace play by the same seat, with
    the same cards (or, for a failed throw, a proper subset of the chosen ones); `failed_detail` covers exactly the failed throws.
- **V, validity, on BOTH arms, before any outcome.**
  - `arm_fault_ceilings` with the one mapping above (play 0, belief 0, bury 1%, declare 1%);
  - `worlds_delivered`: every search record reports the side's play worlds, 256 on the exploiter and 64 on the defender;
  - `completion_shape` (declares at 64) and `outcome_consistency`.
  - Any failure → **DEV_INVALID**, with no outcome computed. A retry needs its own authorization.
- **Head-to-head.** The unit is the paired margin in levels/round: per deal, the mean exploiter-signed level change over its two mirrors.
  The 95% CI comes from a 10,000-rep deal-cluster percentile bootstrap (seed 1). The verdict words are descriptive and open or park
  nothing by themselves:
  - **EXPLOITER_AHEAD** iff the CI lower bound > 0;
  - **DEFENDER_AHEAD** iff the CI upper bound < 0;
  - else **NO_RESOLVED_GAP**.
- **Attribution.**
  - Each deal's whole paired margin goes to its first divergent decision.
  - Cell = class (declare / bury / lead / follow) × trick band (pre-play; tricks 1–5, 6–10, 11–15, 16+) × rank group (first round at
    rank 2; fixed banker 2–6, 7–10, J–A).
  - A cell's contribution = (the sum of its deals' margins) / 600, in levels/round. The cells sum to the head-to-head mean. Each cell's
    95% CI uses the same bootstrap draws.
  - **Reported:**
    - the **top-3 loss cells** (the largest positive contributions, i.e. R48's largest losses) with their CIs, and the top-3 gain cells;
    - the class × trick, class, rank-group and role marginals;
    - the top decile of deals;
    - the 20 largest exploiter wins, with both actions.
  - **Flag:** every joint cell and every class × trick cell whose contribution point estimate is ≥ +0.020. Each flag is a candidate board
    row with a cheap first test. A flag is *resolved* iff its CI lower bound is > 0.
  - **ATTRIBUTION_INVALID** iff a never-diverged deal has a nonzero margin. The head-to-head stands, and no cell is reported.
- **Versus S61 (descriptive).** The head-to-head, the class marginals and every joint cell of either run each go through
  `compare_runs.versus_earlier_run` (`8c2e26fd`). It prints the difference, the independent-runs SE and the normal-approximation 95%
  interval, and carries the caveat *"independent runs, not a paired test; an interval covering 0 does not show equality"*.
  - Each run's SE = its 95% percentile CI width / 3.92.
  - S61's numbers come from `s61_reference.json` (`5d567ceb…`), a projection of the archived S61 `result.json` (`4dd5300e…`).
  - A cell absent in one run counts as 0 there with no SE, and its line says so.
  - `audit_comparison_lines` checks every canonical line.
  - These lines locate change only. The two runs differ in the defender, the exploiter and the deals.
- **Reported (never a condition):** per side, the fallbacks, the exact-stage tallies, decide_play p50 / p95 / p99 / max on the duel host,
  bury and declare seconds, and failed throws; the first-round vs fixed-banker split; and the exploiter's banker / attacker games.

**Resolution.** At 600 deals the head-to-head half-width is about ±0.03–0.04 (S61: ±0.040). A cell's CI is roughly ±0.03 × √(its share
of the deals), so the 0.02 flag resolves only for a large or a heavily one-sided cell.

## Claim limits

- This is not a strength claim for any servable candidate. The exploiter is R48 at a lifted budget on the duel host and is not servable;
  Fly's shared CPU runs a 3 s budget. There is no release, deploy, latency or memory claim.
- The attribution locates; it does not decompose causally. A deal's margin includes every later decision of both teams. The top-3 cells are
  chosen by their point estimates, and their CIs are not selection-adjusted.
- The read does not identify any single knob's effect (widths, exact caps, time, or no lgfd). It is never pooled with a screen or with S61.

## Seeds (`s69_exposure/`)

- Lane `311060910 + 600`, rehearsal `311960000 + 36`, local smoke `311970000 + 4`.
- `seed_windows.py check` (`--purpose screen` and `other`, registry `7923c65d` at `d33bfd70`): rc 0 for all three. The positive control
  (runPVS1r46) is refused with rc 2 (`registry_check.local.txt`).
- `seed_windows.py clear` (`clear.local.txt`), in the form of Codex's R48 clearance:
  - against the R48 play checkpoint `GEN5-PROD-SOFT-allPV-plusMCLCB-496k-SMV3/best.pt` (`3e89e86f`) with `--follow-init`: CLEAR, 0
    overlaps across 2 lineage nodes, controls 0/64, 60/64, 0/64, 56/64. The JS-M1 link is unresolved at its train-out path, so the run
    uses `--allow-unresolved`.
  - against that JS-M1 ancestor from its sha-identical copy (`a5248cc5`): CLEAR, control 62/64.
  - S58's training deals (the registered runPVS*r46 windows and production logs) all lie below 6.2e7 (Codex's R48 clearance).
- Reservation scans on cloud (91 records) and perf (65): no record overlaps any s69 window, and no s69-band token appears
  (`reservations_scan.hosts.txt`).
- The block lies above every earlier lane window: S61 218060910, S63–S66 242xxxxxx, h1a / m28 272xxxxxx, v106sc8 250xxxxxx.

## Reading

Once, after `LANE DONE`, on cloud, with the reader staged beside its pinned helpers:
`/root/gen-hybrid/server/.venv/bin/python -B /root/claude-s69/s69_read_r2.py /root/vol-dev-claude-s69-r48-20261026 /root/claude_s69_screen.status /root/claude_reservations/s69_r2.json <out.json>`.

— Claude
