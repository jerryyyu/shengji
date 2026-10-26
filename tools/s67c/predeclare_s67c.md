# Predeclaration: s67c, ONE powered fresh-only DEV of R48 + the pair / tractor challenger (`-sc8p`) vs R48 as served, 3,920 deals, on shengji-perf

Written 2026-10-26 (UTC) by Claude, before any s67c lane deal is played, before staging, building, arming or any RELEASE. The reader
(`s67c_read.py`) evaluates the read exactly as written here.

**Authority.** Jerry, 2026-10-25 in Claude's session: "What about trying all the non throws, I don't think win is enough to deploy".
Scope: ONE powered, fresh-only DEV of the sc8p candidate against R48 as served, on perf; 3,920 deals; a single look; no deploy authority.
The standing run authorization (2026-09-30 / 2026-10-14) covers the DEV run itself. The RELEASE still needs Codex's non-author PASS.

**What S67c asks.** S66b read R48 + the singleton challenger (`-sc8`) at **+0.0165 [+0.0042, +0.0287]** levels/round on 3,920 fresh deals
(DEV_PASS, 1075/6395802322). The S67 challenger (`-sc8p`, `server/shengji/eval/pair_challenger.py` at `8a50fe8a`, branch
`claude/s67-pair-challenger` = PR #1153's `eb0975da` + one commit) widens the probe's omitted pool from singles to every one-component
lead: singles, pairs and tractors; throws stay out. S67 Stage A (offline, M28 held-out leads) read pair + tractor admission of the expert
lead at +3.85 pp [+2.61, +5.21] over sc8, under its +5 pp bar (FAIL; Stage B parked; tractors carry no headroom). S67c is a new row, run on
Jerry's in-session direction: does R48 + sc8p, under the served budget, beat R48 as served at the same bar S66b passed?

## Unchanged from s66b (reviewed, PASSed, LANE DONE 2026-10-25T09:11:02Z)

- The harness `exploit_duel_s61.py` (`b15d292f…`) and `hypotheses.py` (`4365a15d…`), byte-identical, now staged read-only BESIDE the
  adapter in `/root/claude-s67c/` (the adapter imports both from its own directory; Codex 1075/6405786268); fly.toml (`1fcb2fbf…`, byte-identical at `8a50fe8a`; R48 as served); the packages (smv3out, js-m1, S58).
- The launcher's guards, waits, S17 handshake (adopts the outstanding pause from s66b's handoff `/root/claude-s17-handoff.s66b`), host
  lock, legacy peers, cleanup / signal blocks, child form, fresh-only flow and seal; 14 workers; the r2 rank-mixed plan per deal;
  3,920 deals; stop / backstop 18,000 / 18,010 s.
- The reader's input binding, status binding, integrity gates (except the probe gate), validity checks and ceilings, the bootstrap and
  the bar.

## Changed (this packet only)

| what | s66b | **s67c** |
|---|---|---|
| candidate | `singleton_challenger.py` at `eb0975da` (`1c963fd1…`), `candidate_from_env`, `-sc8`, `SingletonChallengerBuryBot` | `pair_challenger.py` at `8a50fe8a` (`785c7f72…`) over its base `singleton_challenger.py` at `8a50fe8a` (`c0b07645…`), `pair_candidate_from_env`, `-sc8p`, `PairChallengerBuryBot` |
| tree | `/root/claude-sc8-src-eb0975da` (built) | `/root/claude-sc8p-src-8a50fe8a` (a fresh clone, built on perf by `claude_build_sc8p_perf.sh`; the three extension pins are filled from its build log) |
| adapter | `s66_sc8_adapter.py` (`80e0e7f8…`) at `/root/claude-s66dev/`, beside the harness | `s67_sc8p_adapter.py` (`9bf5f0c3…`) at `/root/claude-s67c/`, beside its own staged copies of the harness and hypotheses: the same harness replacement, row key `sc8p`, 9 fields per exploiter decision (+ added_kind, pool, played_kind) |
| sentinel | `S66_EXPLOITER=sc8` | `S66_EXPLOITER=sc8p` |
| lane / paths | `s66b`; `/root/vol-dev-claude-s66b-r48-20261025`; … | `s67c`; `/root/vol-dev-claude-s67c-r48-20261026`; `/root/claude_s67c_screen.status`; `/root/claude_s67c.RELEASE` / `.HOLD`; `/root/claude_reservations/s67c.json`; `/root/claude-s17-handoff.s67c`; the reader at `/root/claude-s67c/s67c_read.py` |
| seed block | 242860910 … 242864829 | **243260910 … 243264829** (fresh) |
| reader probe gate | `sc8_gate` (6 fields) | `sc8p_gate` (9 fields: the six s66b rules plus the kind / pool / card-count rules), the swap rate by lead kind |

## The read (written before launch; one arm, ONE look)

Unit: the paired margin in levels per round, per deal the mean exploiter-signed level change over its two mirrors. The CI is the 95%
percentile interval of a 10,000-rep deal-cluster bootstrap (numpy default_rng, seed 1).

**The bar, verbatim:** one look on this run alone; mean ≥ +0.015 levels/round and deal-cluster CI lower > 0; zero play/belief fallbacks
both sides; every exploiter decide_play ≤ 3.0 s; report swap rate by lead type (single/pair/tractor) and decide_play vs R48; S66b's
+0.0165 compared descriptively only; state power at +0.017 from S66b's observed variance.

- **Single look, fresh-only.** The reader runs once, after `LANE DONE`, on the sealed output. No interim read of a partial `duel.jsonl`,
  no extension of the block, no rerun. The decision uses this run's 3,920 deals alone; nothing is pooled with S66 / S66b.
- **DEV_PASS** iff the paired mean ≥ **+0.015** levels/round **and** the CI lower bound > 0; else **DEV_FAIL**.
- **Validity, both sides, before any outcome:** zero play and zero belief fallbacks; bury fallbacks and declare abandons ≤ 1%; every search
  record at 64 worlds; declares complete; outcome consistency; the paired premise; **every exploiter decide_play ≤ 3.0 s**, judged on the
  0.1 ms recording bin's upper bound (`recorded + 0.00005 ≤ 3.0`). Any failure → DEV_INVALID with the named reasons, no outcome.
- **Reported, never a condition:** the swap rate overall and **by lead kind** (single / pair / tractor: the probes offering each kind,
  entered, chosen, the share of leads), the played-lead kinds; **decide_play vs R48** (ratios p50 / p95 / p99 / max, shares past 2 / 2.5 /
  3 s, the max against the budget, probed-lead vs defender-lead quantiles); belief_ms, bury / declare seconds, failed throws, the
  play-time ratio, points with CI, the nonzero share, the splits (rank 2 vs rank ≠ 2, first round vs fixed banker, banker / attacker),
  first divergence.
- **Versus S66b, descriptive only:** S66b's +0.0165 [+0.0042, +0.0287] beside this run's mean, the difference and an independent-runs SE.
  It never decides; the two runs have different deal blocks.
- **Power (from S66b's observed variance):** S66b's 95% half-width 0.01225 on 3,920 deals gives SE ≈ 0.00625 for this run. At a true
  +0.017, P(mean ≥ +0.015) ≈ 0.63 and P(CI lower > 0) ≈ 0.78; the mean floor binds (at this SE, a mean ≥ +0.015 already has CI lower > 0),
  so **PASS ≈ 63%**. At +0.019 ≈ 74%.

**Consequence.** PASS → a rank-mixed screen of R48 + sc8p against R48 as served and a Fly latency check of the sc8p recipe, each its own
packet, then a release decision that is Jerry's. FAIL → S67c parks with its numbers; the S66b sc8 path is unaffected.

## Claim limits

- The bar is against R48, not against sc8. A PASS says R48 + sc8p clears +0.015 on this block; it does not show that sc8p beats sc8. S67
  Stage A moved 0.6% of lead ballots relative to sc8, so most of any measured gain is expected to be sc8's; the difference from S66b
  (independent-runs SE ≈ 0.0088) cannot resolve an sc8p − sc8 effect below about ±0.017.
- Tier i DEV evidence on perf; not a screen, not a release candidate. Duel-host seconds are not Fly serving latency.
- The swap rate and the selected-kind telemetry are descriptive (not reconciled to dtrace).

## Host estimate

s66b: 8,473.6 s for 3,920 deals under 14 workers (2.35 h). S67 Stage A: sc8p − sc8 +3 ms mean per decision, p99 1.30 s vs 1.29 s, so the
same order: about 2.4 h + about 1 min of checks; stop 18,000 s (≥ 2.1×). The build beforehand ≈ 5 min at nice 19 without the lock.
RSS 14 × ~0.2 GiB; memory guard 8 GiB (30.6 GiB free on perf 2026-10-26 00:40Z). The lane takes the shared host lock in arrival order;
S17 stays paused (adopted from s66b's handoff, then handed off as `claude-s17-handoff.s67c`).

## Seeds

- Block: sc8p `243260910 … 243264829` (3,920 deals); smoke (done, Mac, 2 deals) `243160000 … 243160001`.
- `seed_windows.py check 243260910 3920 --purpose screen` from the claude/s67c-screen worktree at origin/main `abf653f8` (registry
  `7923c65d`): rc 0, disjoint from every registered window; the M17 positive control rc 2; S66b / S66 / v106sc8 / S65 / S64 reported as
  unregistered (cleared by position: S66b ends at 242864830, S66 at 242561510, v106sc8 starts at 250060910).
- **Exact-deal clearance**, the S66 command: `seed_windows.py clear 243260910 3920 --checkpoint /private/tmp/h1a_clear/smv3-best.pt
  (sha256 3e89e86f…) --follow-init --allow-unresolved --purpose screen --control-seed 44260910 --control-seed 23260910 --control-seed
  61260910 --control-seed 22260910`: **CLEAR: 3,920 keys vs 1 checkpoint / 2 lineage nodes, 0 overlaps, registry clear; controls 0/64,
  60/64, 0/64, 56/64**; the already-declared JS-M1 ancestor link stays UNRESOLVED (allowed), as in S66 / S66b.
- S67 Stage A used sealed M28 held-out capsules (deal seeds 272090000…, 272180910…, 272190910…, 71000000, 61740910 blocks), far from
  this block.
- Host reservations: read-only scans on perf (64 records) and cloud (91) find no overlap and no 2431xxxxx / 2432xxxxx token. Packet grep
  clean (three numbers inside production decision logs, none in the block).

## Reading

Once, after `LANE DONE`, ON perf (host mode):
`/root/gen-hybrid/server/.venv/bin/python -I -B /root/claude-s67c/s67c_read.py /root/vol-dev-claude-s67c-r48-20261026 /root/claude_s67c_screen.status /root/claude_reservations/s67c.json /root/claude-s67c/s67c_result.json`.
The reader binds the inputs (TRUSTED: the s67c paths and the final launcher's sha256), then reads `<root>/sc8p/duel.jsonl` and
`<root>/SHA256SUMS`. The reader is Claude.

— Claude
