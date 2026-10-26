# Predeclaration: s69r2, S69 revision r2 on fresh seeds (the S61 red-team design against R48, board #1075 row S69), on shengji-cloud

Written 2026-10-26 (UTC) by Claude, after lane s69's single read and **before any s69r2 deal is played** and before any RELEASE. No deal
of the s69r2 block (312060910–312061509) has been played by anything. The reader (`s69r2_read.py`) evaluates the read exactly as written
here. Below this section the text is s69's predeclaration, with the s69r2 values substituted where marked.

## Why r2: s69 read DEV_INVALID (#1075 6422101463)

- **The r1 read.** Lane s69 (launcher `726a8af0`, reader r3 `49b42345`, seeds 311060910+600) ran to LANE DONE: wall 7,440.9 s, max
  single-process RSS 947,860 kB. Its single read returned **DEV_INVALID**, and no outcome was computed.
- **The cause.** The exploiter made **5 play fallbacks in 38,796 decisions (0.013%)** against the predeclared **zero** play-fallback
  ceiling. The defender made 0. Belief, bury and declare faults were 0 on both sides, and worlds were delivered as configured.
- **The telemetry.** The exploiter's decide_play max was 60.06 s, which is the 60 s budget; its p99 was 11.1 s. Its 8-card exact stages
  were abandoned on the soft budget in 124 of 416 leads and 26 of 1,010 follows. The 36-deal rehearsal (max 48.0 s) did not show this
  tail.
- **Why it cannot be re-read.** The read was one-shot: the s69 block is consumed, and it is not re-read under a changed bar. No margin or
  cell of s69 was computed or seen.

## What changes in r2, and nothing else

1. **Fresh seeds.** The lane is `s69r2`, block `312060910 + 600`.
   - It is disjoint from s69's consumed block and from every registered or reserved window: `seed_windows.py check` rc 0; `clear`
     against the R48 lineage CLEAR; reservation scans on both hosts show no overlap (`s69r2_exposure/`).
2. **One common play-fallback ceiling** of **0.1% of a side's decisions**, the same for the exploiter and the defender. This is S68's
   policy, Codex PASS 1075/6421822839.
   - There is one `BAR` mapping, judged by one `validity.arm_fault_ceilings` call: play ≤ 0.1%, **belief 0**, bury ≤ 1%, declare
     abandons ≤ 1%.
   - **Fallback decisions stay in the outcome.** No row, deal or decision is dropped; a fallback decision is played and scored like any
     other.
   - The fallback record cannot tell a deadline expiry from another search error, so the ceiling covers every play fallback. Under this
     ceiling s69's pattern (5 of 38,796, i.e. at most 38 allowed per side) would have read VALID.
   - The symmetry fixture (`test_s69r2_read.py` T2c) shows that the same count gets the same verdict on either side: the cap → VALID with
     the outcome computed, the cap + 1 → DEV_INVALID.
3. **This section, written before any r2 deal.**

**Unchanged:**
- the exploiter config (the 60 s cap included) and the defender (R48 as served);
- `--history`, and the r3 reader's history and multiset checks;
- the read itself: head-to-head, attribution cells, flags, the versus-S61 lines;
- the producer, the tree `/root/claude-main-56` = `d33bfd70` and its build.

The launcher differs from s69's `726a8af0` only in `LANE`, `OUT`, `SEED0` and comment lines, and `run_child` is byte-identical
(`test_s69r2_launcher.sh` §10).

**No new rehearsal.** The child form is unchanged, so two runs on cloud already cover it:
- the r3 host re-rehearsal (12 deals, 213.4 s, peak group RSS 3.58 GB, `rehearsal/host/`);
- s69's full 600-deal run of the same `run_child`: 7,441 s wall, 0.95 GB max single-process RSS, rc 0, LANE DONE.

The full run is the stronger evidence. The 28,800 s stop is 3.9× its wall, and its peak memory fits the 12 GiB MemAvailable guard.

## s69's predeclaration (r2 / r3 revisions included), with s69r2 values where marked

**Revision r2** (2026-10-26, still before any lane deal): the producer runs with `--history`, so every row keeps `buried`, `history`
and `failed_detail`, and S69's top cells can feed same-root replay fixtures. S61's extraction was refused because its producer ran
without it. The reader gains a history gate that refuses a row without these fields or with fields inconsistent with the trace. The
launcher is `claude_s69_r2_cloud.sh`, the reader `s69_read_r2.py`, the reservation `s69_r2.json`. The read, arms, seeds and thresholds
are r1's. The r3 host re-rehearsal (12 deals) measured the cost of `--history`; r1's files are in `superseded-r1/`.

**Revision r3** (2026-10-26, Codex HOLD 1075/6417632636; reader only, before any lane deal): `history_gate` compares cards as
multisets, requires a failed throw's actual cards to be a strict sub-multiset of the attempted ones, and reconciles every
`failed_detail` entry: index a failed throw, not repeated; seat = the trace seat; attempted = the trace's chosen cards; actual = history's
cards. The repaired reader is staged as `s69_read_r3.py`. The launcher (`726a8af0`), producer, rehearsal, seeds and tree are unchanged.

**Why.** Board row S69: where does R48 lose now? S61 ran against release 46, whose top loss cells R48 has since absorbed (S58, dtrx, lgf,
not sc8: R48 does not serve it; sc8 remains an unshipped stackable flag). This lane re-runs the S61 design against R48 to find the gap again. Tier i DEV under `RL_PLAN.md` "Operating modes".

**Authority.** Jerry 2026-10-26 in Claude's session: "The combo and red team sound good to test". That covers tests only, with no deploy.
The RELEASE still needs Codex's non-author PASS of this packet.

## The predeclared read (verbatim, as briefed)

> 600 seat-swapped pairs head-to-head; report head-to-head margin (levels/round) with deal-cluster 95% CI; loss attribution by
> first-divergence cell (decision class lead/follow/bury/declare × trick band × rank group) with each cell's contribution and CI; list
> top-3 cells. Not a strength claim for any servable candidate; exploiter is not servable. Validity: zero play/belief fallbacks both sides
> (or the S61 ceilings, same on both arms), worlds delivered as configured. Comparison lines vs S61 must report difference with its
> interval and the caveat "independent runs, not a paired test".

~~s69 took zero play and zero belief fallbacks on both sides.~~ **s69r2 takes the S61-style option, made common:** play fallbacks
≤ 0.1% of each side's decisions (one ceiling for both arms), zero belief fallbacks, bury ≤ 1%, declare abandons ≤ 1%. Fallback decisions
stay in the outcome.

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
| deals | **600**, seeds **s69r2: `312060910 … 312061509`** (s69: `311060910 …`), the r2 rank-mixed plan per deal (index % 10 ∈ {0,3,5,8}: first round at rank 2; otherwise a fixed banker at rank `RANKS13[index % 13]`), 12 workers |
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
  - `arm_fault_ceilings` with the one mapping above (**s69r2: play 0.1% of each side's decisions**, belief 0, bury 1%, declare 1%);
    the play-fallback count, rate and cap are reported per side;
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

## Seeds (s69r2: `s69r2_exposure/`; s69's text follows the first bullet)

- **s69r2:** lane `312060910 + 600` only (no rehearsal or smoke window). `check` (screen / other) rc 0; `clear` against the SMV3
  checkpoint with `--follow-init` CLEAR (0 overlaps, controls 0/64, 60/64, 0/64, 56/64) and against the JS-M1 copy CLEAR (62/64);
  reservation scans cloud (93 records) / perf (66): no overlap (the only hits are s69's own records on its consumed block, reported).
- s69: lane `311060910 + 600`, rehearsal `311960000 + 36`, local smoke `311970000 + 4`.
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
`/root/gen-hybrid/server/.venv/bin/python -B /root/claude-s69/s69r2_read.py /root/vol-dev-claude-s69r2-r48-20261026 /root/claude_s69r2_screen.status /root/claude_reservations/s69r2.json <out.json>`.

— Claude
