# Predeclaration: s61dev, the paired seat-swapped DEV head-to-head of the S61 exploiter vs release 46 as served, with a loss attribution, on shengji-cloud

Written 2026-10-22 (UTC) by Claude, before any s61dev deal is played, before the cloud tree is built, before staging, arming or any
RELEASE. The reader (`s61dev_read.py`, `analyze`) evaluates the read exactly as written here, and its docstring points to this file.
**Revision r2** (same day, still before any deal; r1 kept in `superseded-r1/`): the exploiter keeps release 46's declare and bury knobs
(the coordinator's decision). S61 hunts play-phase gaps; the declare and bury levers were measured separately (S40's vdea bar failed,
S53's bury read DEV_FAIL); and ×4 declare / bury widths put every first divergence of r1's local deals before the first play. The read,
the seeds and the thresholds are r1's.

**Why.** Board #1075 row S61. Every screen measures an arm against the old MC-LCB control, which averages away the gaps a seat-swapped
opponent hunting release 46's weaknesses would find. The row's DEV test: release 46 vs an exploiter (release 46 + the strongest
DEV-passing levers, deadline lifted), 600 seat-swapped pairs head-to-head, plus a loss attribution over the exploiter's biggest wins
(decision class, trick, rank). The row's bar: report the head-to-head margin with its CI and the top-3 loss classes; any class costing
≥ 0.02 levels/round becomes its own row. This lane is tier i under `RL_PLAN.md` "Operating modes".

**Authority.** The standing run authorization (2026-09-30; 2026-10-14: DEV runs need no permission), Jerry 2026-10-21 "2-5 look good"
(the S61 row among them) and 2026-10-22 "Yes" to build it. It authorizes nothing by itself and carries no release, deploy, latency or
memory claim. The RELEASE still needs Codex's PASS of this packet.

## The arms (existing knobs only; no code change; `arms.py`, `name_probe.py` → `name_probe.out`)

| | defender seats | exploiter seats |
|---|---|---|
| bot | release 46 as served: fly.toml `SHENGJI_BOT` on the tree (`cee55eac…`), its belief package `s17long-e2-763b5e05` mapped to `/root/models` | release 46 + the fifteen pairs of `arms.chosen()` (r2) below |
| name | `pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-vd-vdef-ed7-xf7-xfcompactlevel-r73993d62-bury-hybrid-bwv-cf77a93949b0` (derived MATCH) | `pv-search-491ee4bf-w256-k32-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-ed8-els9000-edn200000000-xf8-xfcompactlevel-rda5aa46f-bury-hybrid-bwv-a7397463b3c0` |

The exploiter, pair by pair:

| group | pairs | source |
|---|---|---|
| R48 keys | `SHENGJI_PV_BELIEF_CKPT=/root/s46r3/pkg/s46-e2-36e2024e.npz`, `SHENGJI_PV_BELIEF_SHA256=36e2024e…` (S46 r3 epoch 2, its stored temperature 1.0071, served unchanged), `SHENGJI_PV_DOOMED_THROW_RESELECT_EXACT_GUARD=1` (dtrx), `SHENGJI_PV_LEAF_GREEDY_FINISH=1` (lgf), `SHENGJI_PV_LEAF_GREEDY_FINISH_EXACT_SKIP=1` (lgfx) | v100lgf's candidate (R47 + lgf + lgfx) |
| play widths ×4 | `WORLDS` 256, `CANDIDATES` 32 | S60's x4 (`s60_arms.base.py` `d8151e32`) |
| deadline lifted | `EXACT_DEEP_CARDS` / `EXACT_FOLLOW_MAX_CARDS` 8 / 8, `SERVING_BUDGET_SECONDS` **48** (S60: 12), `EXACT_LEAD_MAX_SECONDS` 9.0, `EXACT_DEEP_MAX_NODES` / `EXACT_FOLLOW_MAX_NODES` 200M; no `SHENGJI_PV_LEAF_GREEDY_DEADLINE` (no lgfd) | S60's x4, the play budget raised for lgf (bench) |
| declare and bury: release 46's (r2; no override) | `VALUE_DECLARE_WORLDS` 64 (default), `BURY_MODEL_WORLDS` 32 (default), `BURY_WIDE_K` 64 and `BURY_SERVING_BUDGET_SECONDS` 2 (fly.toml) | `arms.DECLARE_BURY_KEYS` are absent from `chosen()` (asserted) |
| latency switches | `SHENGJI_PV_ENCODE_PREFIX_CACHE=1`, `SHENGJI_PV_LEAF_GREEDY_STREAM=1` | decision-identical by contract (no name, payload or digest; no card changes on a completed search) |

`exploiter(4)` minus the R48 keys equals S60's x4 pairs exactly (asserted in `arms.py`); `chosen()` is `exploiter(4)` without the four
declare / bury keys, with the 48 s budget and the switches. The latency switches are read where a bot is built,
so the harness applies them to the exploiter's bots only (`variant_factory`, edit 3), and the child runs with all three switch variables
removed from its environment (`env -u`). `check_names` builds one bot per side on the host and asserts that the exploiter has both switches,
that the defender has none, and that each side binds its own belief package.

**Why ×4 play widths at 48 s, and not ×2 or ×1** (bench below; measured on r1's arm, whose play knobs r2 keeps). At 12 s, ×4 fell back on 11 of 124 exploiter decisions (8.9%, far above the 0.1% V
ceiling). At 48 s with the switches, it fell back on none: the slowest decision took 6.3 s in the bench and 10.0 s in r1's smoke (an 8-card
exact follow). The switches cut ×4's cost 2.4× (exploiter decide time 286 → 117 s on the same two deals) and its peak memory from 1.24 to
0.77 GiB, with identical traces on all four mirrors (`bench/e4b48` vs `bench/e4s48`). r2 (release 46's declare / bury) runs in about 2.5 h (below). ×2 at 12 s also
fit (0 fallbacks, max 4.2 s, about 1.4 h), but the task rule takes the largest multiple that fits in about 8 h.

## The duel

| | |
|---|---|
| harness | `exploit_duel_s61.py` = s60dev's `exploit_duel_s60.py` (`ed28c595…`) + 9 asserted edits (`make_s61dev_duel.py`, `s61dev_duel_vs_s60.diff`). It adds the row key `dtrace`: one `[phase, seat, trick, lead, hand, cards]` entry per decision in the round's order (D = a declare call while dealing, F = a final declare call, B = the bury, P = a play), read-only. It also applies the exploiter-only latency switches. dhist (19 fields), dsecs, `declare_recs`, `bury_rec`, the r2 plan, the seat seeds and the mirror layout are s60dev's. `hypotheses.py` is verbatim (`4365a15d…`), with `--arm identity` (every `fired` count 0) |
| pairing | every deal is played twice with the teams swapped. The per-(deal, seat) seeds do not depend on the arm or the mirror. Release 46 against itself diverges nowhere: in the bench, both r46-vs-r46 deals had identical mirror traces and a margin of exactly 0 |
| tree | `/root/claude-main-54` = origin/main `4a81641c…`, a fresh cloud build (`BUILD_RC=0` in `/root/claude-main-54-build.log`; the three extension pins are filled after the build) |
| deals | **600**, seeds `218060910 … 218061509`, 14 workers, the r2 rank-mixed plan per deal. Hard stop 28,800 s, backstop 28,810 s |
| host | shengji-cloud (16 vCPU EPYC Genoa), python `/root/gen-hybrid/server/.venv/bin/python` (3.14), the shared mkdir host lock `/root/.claude-host.lock`, no S17 handshake. Memory guard: MemAvailable ≥ 16 GiB |

## The read (written before launch; the reader evaluates it as an outcome)

The unit is the paired margin in levels per round: each deal's mean exploiter-signed level change over its two mirrors. CIs are 95%
percentile intervals from one 10,000-rep deal bootstrap (seed 1). The attribution's cell CIs use the same draws.

- **Binding (refuses).** The status has exactly one terminal line `<stamp> s61dev DEV output sealed; rc/status only (strength
  qualification is reader-owned); LANE DONE` and no ABORT: or REFUSING: line (`reader_lib.terminal_line`, NO_TAIL). Before it come one
  DEV start line naming both pinned arms and one `DEV END rc=0` line. The input's sha256 equals its `./duel.jsonl` line in the lane's
  `SHA256SUMS`.
- **Integrity (refuses).** s60dev's checks, unchanged:
  - arm identity, no fired override, the two pinned names, 600 seeds × 2 mirrors with no duplicate, missing or extra row, and the r2 plan;
  - the 19-field dhist row schema on both sides, `exact_deep_cards` 8 on the exploiter and 7 on the defender, the reconciliations, no
    defender 8-card stage, at least one complete exploiter 8-card lead and follow;
  - the declare and bury producer shapes at each side's world counts (both sides: declare 64, bury 32, K ≤ 64).

  Plus the trace (`trace_gate`):
  - the order: 100 D, then F for seats 0..3 at hand 25, then B by the banker (33-card hand, 8 cards), then plays in tricks of 4 (the
    leader, then leader+1..3), every field typed;
  - the non-empty D / F entries equal the row's `declares`;
  - each seat's hand falls by the cards it played. A failed throw (in `failed_throws`) plays fewer cards than chosen, so its next hand is
    only bounded. Every hand ends empty;
  - per side, the plays equal dhist in count and lead flag, with hand ≤ dhist's max hand.

  Per deal, the first entry where the two mirrors' traces differ must differ in its cards only, never in phase, seat, trick, lead or hand.
- **V, validity, on BOTH arms (`reader_lib/validity.py`, before any outcome).**
  - `arm_fault_ceilings`: play fallbacks ≤ 0.1% of the side's decisions, belief fallbacks ≤ 1% of its search decisions, bury fallbacks
    ≤ 1% of its buries, declare abandons ≤ 1% of its declare evaluations;
  - `worlds_delivered`: every search record reports the side's play worlds (256 / 64);
  - `completion_shape`: an evaluated declare completed all of the side's worlds;
  - `outcome_consistency`: every row obeys the engine's level rule.

  If any of these fails, the verdict is **DEV_INVALID** with the named reasons, and no outcome is computed. Any retry needs its own
  authorization.
- **Head-to-head (the row's margin with its CI).** **EXPLOITER_AHEAD** iff the CI lower bound is > 0. **DEFENDER_AHEAD** iff the CI upper
  bound is < 0. Otherwise **NO_RESOLVED_GAP**. These are descriptive words: none of them opens or parks a lane by itself.
- **Attribution (the row's loss classes).**
  - Each deal's whole paired margin goes to its first divergent decision: the first trace index where the mirrors differ. Up to that
    index both mirrors played the same round, so at that index the same seat acts in the same state, once as the exploiter and once as
    release 46.
  - The cell of a decision is class × trick bucket × rank group:
    - class: declare (D / F), bury, lead, follow;
    - trick bucket: pre-play, or tricks 1–5, 6–10, 11–15, 16+ (by the 0-based trick index: < 5, < 10, < 15, otherwise);
    - rank group: first round at rank 2, or fixed banker at 2–6, 7–10, J–A.
  - A cell's contribution = (the sum of its deals' margins) / all 600 deals, in levels/round. The cells sum to the head-to-head mean.
  - **Reported:**
    - the top-3 loss cells (the largest positive contributions, i.e. release 46's largest losses) with CIs, and the top-3 gain cells;
    - the class × trick marginal, plus the class, rank-group and class × role marginals;
    - the top decile of deals by margin (60 deals, ties by seed) with their cell counts and contributions;
    - the 20 largest exploiter wins, with both actions at the divergence.
  - **Flag:** every class × trick × rank cell, and every class × trick cell, whose contribution point estimate is ≥ +0.020 levels/round.
    Each flagged cell is a candidate board row, and it is marked *resolved* iff its CI lower bound is > 0.
  - **ATTRIBUTION_INVALID** iff a deal whose mirrors never diverged has a nonzero margin (the premise is broken). The head-to-head
    stands, and no cell is reported as a finding.
- **Reported (never a condition):** per side, the fallbacks, the exact-stage outcomes at max hand 8 and ≤ 7, decide_play p50 / p95 /
  p99 / max, bury and declare seconds, and failed throws. Also descriptive: the first-round vs fixed-banker split and the exploiter's
  banker / attacker games.

**Resolution.** At 600 deals the head-to-head CI half-width is about ±0.03 (s60dev's read: ±0.036). A cell's CI is narrower, roughly
±0.03 × √(its share of deals). The 0.02 flag can therefore be resolved only for a cell carrying a large share of the deals or a large
mean margin.

## Claim limits

- **Where the first divergence falls.** r1's arm (×4 declare and bury widths) diverged before the first play in all 4 local deals. r2's
  arm keeps release 46's declare and bury knobs, and all 4 of its local deals (2 bench + 2 smoke) first diverged in play (tricks 1–3:
  2 leads, 2 follows). A deal can still diverge at a declare or bury (the S46 r3 belief package also feeds those decisions), and such
  deals are attributed there. The read says nothing about declare or bury levers, which S40 and S53 measured.
- The attribution locates; it does not decompose causally. A deal's margin includes every later decision of both teams after the
  divergence. The top-3 cells are chosen by their point estimates, and their CIs are not selection-adjusted.
- The exploiter is not a servable recipe. Its 48 s budget is lifted on the duel host, and Fly's shared-cpu-1x is about 2.45× slower than
  perf. The read makes no release, deploy, latency or memory claim, and it is not R48 at the served budget (v100lgf is that test).
- The exploiter bundles the R48 keys with S60's ×4. The read does not identify the components' effects by subtraction from s60dev,
  v100lgf or any other read.
- The DEV read is tier i evidence and is never pooled with a screen.

## Bench (this Mac, Apple M4, otherwise idle; nice 10; one worker per process; `bench/bench_summary.txt`)

| arm (2 deals 217960010–11 unless noted) | wall / deal | exploiter decide_play p50 / p99 / max | play fallbacks | peak RSS |
|---|---|---|---|---|
| r46 vs r46 | 7.6 s | 0.055 / 0.11 / 0.13 s | 0 | 121 MiB |
| e1 (×1 widths, 12 s) | 17.6 s | 0.09 / 0.89 / 0.91 s | 0 | 277 MiB |
| e2 (×2, 12 s) | 46.3 s | 0.19 / 3.87 / 4.22 s | 0 | 911 MiB |
| e4 (×4, 12 s) | ~150 s | 0.51 / 12.04 / 12.04 s | **11 of 124** | n/a |
| e4, 48 s | 149 s | 0.40 / 13.5 / 13.8 s | 0 | 1,237 MiB |
| e4, 48 s + switches (bench: process-wide) | 62.8 s | 0.17 / 5.5 / 6.3 s | 0 | 792 MiB |
| r1 chosen (×4 declare / bury), smoke 217960000–01 | 110.7 s | 0.29 / 6.7 / 10.0 s | 0 | 968 MiB |
| **r2 chosen, bench** (exploiter-only switches) | 76.4 s | 0.22 / 6.2 / 13.3 s | 0 | 758 MiB |
| **r2 chosen, smoke** 217960000–01 | 87.3 s | 0.20 / 5.9 / 6.5 s | 0 | 838 MiB |
| S60 x4 alone (calibration) | 28.0 s | 0.19 / 1.66 / 2.86 s | 0 | 155 MiB |

The bench rows for e1, e2 and e4 ran the harness before edit 3. Edit 3 touches only the latency switches, and those arms pass none.

**Host estimate.** Host speed per worker under 14 workers, from two measured pairs:
- s60dev's x4 ran 600 deals in 3,081 s on 14 perf workers (71.9 worker-s per deal), against 28.0 s here: a factor of 2.57;
- v97dev's release-46-cost duel ran 17.0 worker-s per deal on perf, against 7.6 s here: a factor of 2.24.

shengji-cloud is the same 16-vCPU EPYC Genoa class. The r2 arm averages 81.8 s per deal over its 4 local deals, so at 2.57 the run
takes 600 × 81.8 × 2.57 / 14 ≈ **9,000 s ≈ 2.5 h**. At the 1.5–2× rule of thumb it would take 1.5–1.9 h. The 8 h hard stop covers 3×
the 2.5 h figure.
- The slowest local decision (13.3 s, a base search above 8 cards in the bench) maps to about 34 s on the host, against the 48 s budget:
  a 1.4× margin, the tightest number in this packet. A host tail above 48 s is a play fallback, and V allows 0.1% of each side's
  decisions. The 8-card lead stage keeps its 9 s cap, and the follow stage soft-stops at 0.8 B = 38.4 s.
- Bury and declare are release 46's (0.24 s and 0.05 s max here).
- Memory: 14 × 0.82 GiB ≈ 11.5 GiB, against the 16 GiB guard.

## Seeds

The block is `218060910 … 218061509` (600). The smoke window is `217960000 … 217960001` and the bench window `217960010 … 217960021`
(`s61dev_exposure/`).
- `seed_windows.py check … --purpose screen` from the worktree `claude-s61` at `4a81641c` (the tool has no `dev` purpose; s60dev used
  `screen`) gives rc 0 "disjoint from every registered window" for all three. The positive control (the M17 block) is refused (rc 2).
- The block is above every lane window in the packets: s60dev 196060910+600, v103s58 214060910 + 100000·i (i ≤ 9), and v100lgf
  210060910… It is also far above every registered corpus interval (runJS, runPV, runPVC, runPVE, runPVS r46: all < 62,000,000).
- Packet grep (`packet_grep.local.txt`): no token in the three windows.
- **Open:** the reservation scans on both hosts (`reservations_high.py` via `ssh <host> python3 -`). They are read-only and have not
  run, because this packet was built without ssh.

## Reading

Once, after `LANE DONE`, on the sealed output:
`python3 s61dev_read.py /root/vol-dev-claude-s61dev-r46-20261022/duel.jsonl /root/claude_s61dev_screen.status /root/vol-dev-claude-s61dev-r46-20261022/SHA256SUMS <out.json>`.
The reader loads `row_schema.py`, `validity.py` and `reader_lib.py` at their pinned sha256s (beside it or in `reader_lib`) and prints its
canonical lines.

— Claude
