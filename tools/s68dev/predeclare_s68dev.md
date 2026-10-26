# Predeclaration: s68dev, two fresh-only DEV arms of the S68 combo candidate vs R48 as served, 3,920 deals each, on shengji-perf

Claude wrote this on 2026-10-26 (UTC). It predates every s68dev lane deal, the staging, the build, the arming and any RELEASE. The reader
(`s68dev_read.py`) evaluates the read exactly as written here.

**Authority.** Jerry, 2026-10-26 in Claude's session: "The combo and red team sound good to test". The scope is testing only: no release
and no deploy authority. A combo release is Jerry's call. The standing run authorization (2026-09-30 / 2026-10-14) covers the DEV run
itself. The RELEASE still needs Codex's non-author PASS on the exact launcher and its dependency cone.

**What S68 asks.** On 2026-10-26 Jerry declined to release sc8 alone (S66b DEV +0.0165 [+0.0042, +0.0287], 1075/6395802322). He said
"The win isn't big enough". The composition survey (`s68_survey.md`) found three levers that compose on R48 and have positive measured
points: sc8, the capacity-aware belief draw bwc, and wider play search (w96k12). Does a stack of them reach a release-sized gain over R48
as served?

## The two arms (each judged alone; the defender in both is R48 as served, fly.toml `SHENGJI_BOT`, full budgets)

| arm | exploiter | exploiter env (the launcher's `arm_env`) | exploiter name | seeds |
|---|---|---|---|---|
| **b** | R48 + sc8 + bwc at the served budgets (3 s, lgfd 2000, bury 2 s), W64 / K8 | `S66_EXPLOITER=sc8 SHENGJI_PV_BELIEF_CAPACITY=1` | `pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-bwc-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-red111e2f-bury-hybrid-bwv-9125072c7686-sc8` | 243660910 … 243664829 |
| **a** | R48 + sc8 + bwc + W96 / K12, at the Fly-equivalent **half** budget on the exploiter side (play 1.5 s, lgfd 1000, bury 1 s) | b's + `SHENGJI_PV_WORLDS=96 SHENGJI_PV_CANDIDATES=12 SHENGJI_PV_SERVING_BUDGET_SECONDS=1.5 SHENGJI_PV_LEAF_GREEDY_DEADLINE=1 SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS=1` | `pv-search-491ee4bf-w96-k12-div-rc-whl-whd-bw-bwc-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd1000-ed7-xf7-xfcompactlevel-r99a6f365-bury-hybrid-bwv-533c84747dc9-sc8` | 244060910 … 244064829 |

- **The half budget.** Fly measured about 2.0× slower than perf (v104fly). Arm a's exploiter therefore runs on perf with half the served
  outer budgets. This measures the strength that survives Fly's truncation. S64's +0.0242 [−0.0092, +0.0583] for w96k12 was taken at the
  full served budget, where its perf p95 was 1.44 s (about 2.9 s on Fly). The defender keeps the full budget: R48's perf p99 is about
  0.7 s (about 1.4 s on Fly), so R48 on perf at full budget stands in for R48 on Fly. The inner exact caps are unchanged (as in
  codex/s58-combo's half-budget-lgfd1000 profile).
- **Arm order.** The lane runs b first, then a.
- **The code.** Both sides run from the candidate tree `8b6ead10` = main `d33bfd70` + `claude/s68-bwc` `64159b86` (bwc, off by default;
  R48's name and digest unchanged when off) + #1156's `39d514cc` (sc8's opt-in serving registry; the screened algorithm unchanged).
  `check_names` verifies, through the staged adapter: each arm's config diff against the defender, the exploiter's time settings and
  widths, the capacity proposal on the exploiter only, the same S58 package and temperature, and the latency switches on both sides.

## Unchanged from s67c / s66b (reviewed, PASSed, LANE DONE)

- The harness `exploit_duel_s61.py` (`b15d292f…`) and `hypotheses.py` (`4365a15d…`). The adapter is s66b's `s66_sc8_adapter.py`
  (`80e0e7f8…`), verbatim. For an overridden env it re-derives the baseline name before building the challenger through the tree's
  `candidate_from_env`. All three are staged read-only, side by side, in `/root/claude-s68dev/`.
- The packages: smv3out, js-m1 and S58.
- The launcher (from s67c's final `2bc24cee`): the guards, waits, S17 handshake (adopting the outstanding pause from s67c's handoff),
  host lock, legacy peers, cleanup and signal blocks, child form, fresh-only flow and seal; 14 workers; the r2 rank-mixed plan per deal.
- The reader (from s66b's `8c0b32f4`): the input binding, status binding, integrity gates, validity checks and ceilings, the bootstrap.

## The read (written before launch; one look per arm)

Unit: the paired margin in levels per round. For each deal it is the mean exploiter-signed level change over the deal's two mirrors.
The CI is the 95% percentile interval of a 10,000-rep deal-cluster bootstrap (numpy default_rng, seed 1).

**The bar, per arm, verbatim:** DEV_PASS iff mean ≥ +0.030 levels/round and CI lower > 0, with zero play and belief fallbacks and
every decision ≤ 3 s. Each arm's mean and CI are reported regardless. Arm a vs arm b is reported descriptively through
`reader_lib/compare_runs.py`.

- **One look, fresh-only.** The reader runs once, after `LANE DONE`, on the sealed output. There is no interim read, no extension and no
  rerun. Nothing is pooled with S64, S66 or S66b.
- **DEV_PASS** for an arm iff its paired mean is at least **+0.030** levels/round **and** its CI lower bound is above 0. Otherwise
  **DEV_FAIL**. Each arm's verdict stands alone. There is no multiplicity adjustment; with two arms, the chance that at least one passes
  by noise is higher than either arm's own rate.
- **Validity, both sides, before any outcome:**
  - zero play and zero belief fallbacks;
  - bury fallbacks and declare abandons at most 1%;
  - every search record at the arm's play worlds (b: 64 / 64; a: 96 exploiter / 64 defender);
  - declares complete;
  - outcome consistency;
  - the paired premise;
  - **every exploiter decide_play ≤ 3.0 s** on the duel host, both arms, judged on the 0.1 ms bin's upper bound.

  Any failure gives DEV_INVALID, with the named reasons and no outcome. In arm a, a search that runs past its own 1.5 s budget writes a
  fallback record, which the zero-fallback ceiling counts. **The half-budget arm is therefore DEV_INVALID if even one of its plays expires
  its budget.**
- **Reported, never a condition:**
  - each arm's mean and CI, whatever the verdict;
  - the swap rate (singleton entered / chosen);
  - decide_play against R48: the ratios, the shares past 1 / 1.5 / 2 / 2.5 / 3 s, and the exploiter's decisions past its **own** budget;
  - belief_ms, bury and declare seconds, failed throws, the play-time ratio, points, the nonzero share;
  - the splits (rank 2 vs rank ≠ 2, first round vs fixed banker, banker / attacker) and first divergence;
  - arm a vs arm b and arm b vs S66b (sc8 alone, +0.0165 [+0.0042, +0.0287]) via `compare_runs.versus_earlier_run`. These are
    independent runs, not a paired test, and an interval covering 0 does not show equality.
- **Power (from S66b's observed variance):** S66b's 95% half-width of 0.01225 on 3,920 deals gives SE ≈ 0.0063 per arm. The +0.030 mean
  floor binds: at this SE, a mean of +0.030 already has its CI lower bound above 0. So P(PASS) ≈ P(mean ≥ +0.030):
  - **about 50% at a true +0.030**;
  - about 17% at a true +0.024;
  - about 83% at a true +0.036.

  The survey's expectation was about +0.020 to +0.024 for arm b and about +0.025 to +0.033 for arm a at the full budget (lower at half
  budget), so a FAIL is the likely outcome even when the stack helps.

**Consequence.** A PASSing arm leads to a rank-mixed screen of that recipe against R48 as served and the Fly in-machine latency check,
each its own packet; then any release decision is Jerry's. A FAIL is recorded on the row with its numbers. bwc remains a default-off flag
whatever happens.

## Claim limits

- Tier i DEV evidence on perf. Neither arm is a screen or a release candidate. Duel-host seconds are not Fly serving latency, and the
  half budget is a 2× perf/Fly assumption (v104fly), not a measured host equivalence.
- Each arm is a bundle: it does not attribute its gain to sc8, bwc or the width. Arm b vs S66b and arm a vs arm b are independent-runs
  differences with an SE of about 0.009, so they cannot resolve a component smaller than about ±0.018.
- bwc's offline precheck (Mini, 2026-10-26) ran on heuristic-play states, not R48 play. On 6,623 non-banker states with a hidden kitty,
  S58's trump leak was 0.178 [0.173, 0.183] per world under the plain draw and 0.099 under bwc, a cut of 44.2% [43.2, 45.3]. Its
  gameplay effect on S58 is what arm b measures, bundled with sc8.

## Seeds

- Blocks:
  - arm b: `243660910 … 243664829`;
  - arm a: `244060910 … 244064829`;
  - the perf rehearsal (throwaway, not read): `243570000 … 243570055`.
- `seed_windows.py check … --purpose screen` (registry `server/runs/seed_windows.json` at main `d33bfd70`) gives rc 0 for all three. The
  M17 positive control gives rc 2. S67c, S66b and the S64 span are unregistered and clear by position. See
  `s68dev_exposure/registry_check.local.txt`.
- **Exact-deal clearance**, using the S66 / S67c command (`seed_windows.py clear <s0> 3920 --checkpoint /private/tmp/h1a_clear/smv3-best.pt
  --follow-init --allow-unresolved --purpose screen --control-seed 44260910 --control-seed 23260910 --control-seed 61260910
  --control-seed 22260910`), gives **CLEAR for both blocks**: 3,920 keys each, 0 overlaps, registry clear, controls 0/64, 60/64, 0/64 and
  56/64. The JS-M1 ancestor link stays UNRESOLVED (allowed, as before). See `s68dev_exposure/exact_clear.local.txt`.
- Host reservations: read-only scans on perf (65 records) and cloud (91) find no overlap and no 2435xxxxx … 2440xxxxx token. See
  `s68dev_exposure/reservations_high.hosts.txt`.

## Host estimate

See `rehearsal/host/rehearsal_summary.json`, which records the bounded perf rehearsal of the exact child form (filled after the
rehearsal; written before any lane deal). The per-arm stop `KILL_AFTER` must cover the projected per-arm wall.

## Reading

The reader is Claude. It runs once, after `LANE DONE`, ON perf (host mode):

`/root/gen-hybrid/server/.venv/bin/python -I -B /root/claude-s68dev/s68dev_read.py /root/vol-dev-claude-s68dev-r48-20261026 /root/claude_s68dev_screen.status /root/claude_reservations/s68dev.json /root/claude-s68dev/s68dev_result.json`

The reader first binds the inputs (TRUSTED: the s68dev paths and the final launcher's sha256). It then reads `<root>/b/duel.jsonl`,
`<root>/a/duel.jsonl` and `<root>/SHA256SUMS`.

— Claude
