# Fleet job ledger — mini (this machine)

The Air keeps its own at `~/Projects/shengji-compute/JOBS.md`, which is also
the inter-agent mailbox. Keep one authoritative running section here.

## RUNNING

Nothing at this snapshot. Package H is closed; the fleet should move to the
bounded S0 confidence-search implementation and teacher-v1 preflight in
`HANDOFF_ACTIVE.md`, not wait on further generic certification work.

**SAMPLER CERTIFICATE — CURRENT.** `server/runs/logs/certify_sampler_v3.json`,
git `aea3774`, clean tree, compiled ACTIVE, strict voids ON. 1,500 states at
500/500/500 across original/late/deep; 36,000 requested = accepted; 0 rejected,
0 invalid, all four skip counters 0; 120/120 toys reachable with the real deal
reached in all. `certified: true` with `scope_failures: []`. Artifact SHA-256:
`e31e67f9aeb4739aa598faa66051ec4004fd47751b297457242dc95a30cc224c`.

SUPERSEDED, and none of them was original+late+deep certification: `eea78d2`
(original-only — one global counter across ordered paths starved `late`),
`c1ceca1` (same defect plus 40/40 toys against a registered 120), and the dirty
v2 run (generated pre-commit, `tree_dirty=true`).

Codex reviewed and **ACCEPTED / CLOSED** package H on 2026-08-05. Posterior
fidelity and global constructive-dealer completeness remain separately open;
neither blocks the strength queue.

## FINISHED — decision-sensitivity screen (Codex's unblocking condition), 06:05

Does the sampler's posterior bias change WHICH ACTION is chosen? Fixed value
table per (action, world) so rollout noise cannot vary; compare argmax under the
exact physical posterior, N=30 from the real sampler, and N=30 from the exact
posterior as a CONTROL that absorbs Monte Carlo noise.

- 30 decision-LIVE states, 600 reps: excess disagreement `-0.0066 +/- 0.0169`,
  excess regret `-0.0098 +/- 0.0171`. Both include zero; sign flipped between
  the 12- and 30-state blocks, so read neither point estimate.
- **54 of 84 enumerable states are DECISION-DEGENERATE** — every candidate
  identical on every world. The harness excludes and counts them and REFUSES if
  none remain, because there a broken probe and a perfect sampler both print
  0.000.
- NOT harmless per state: only 9/30 live states disagree at all, with excess
  from `+0.158` (bias nearly doubles the error rate) to `-0.160` (bias helps).
- Fill-failure retry reweighting RULED OUT here: 0 failed draws in 540,000 attempts with 0 failed draws (recorded in the v2 artifact)
  empty `reject_cause`.
- Screen, not preregistered; population is small, endgame-heavy and
  unrepresentative of the deep-lead states the pilot scores. Gate NOT called.

## FINISHED — reference repair + residual attribution, 2026-08-05 03:10

Physical-deal reference implemented and brute-force verified (`AABB 2/2` -> 6,
`AABBCC 2/2/2` -> 90). All blocks reweighted from stored histograms, no
resampling. Weighted splits CONFIRMED at `-0.0600 +/- 0.0310` against the
corrected reference (larger than the `-0.0514` flat figure, so not a reference
artifact). `PHYSICAL_FILLS` adds `-0.0031 +/- 0.0048` — below resolution, 22/24
states unchanged, 0 worse. Residual attributed: split-choice TV `0.0697` vs
card-choice `0.0330`, so it remains in `_splits` after weighting. Off-support
sampled mass is 0.0000 everywhere. Nothing adopted, all flags OFF.

## FINISHED — 103M `mc` vs `mc-prefix` bot-layer contrast (Jerry's ask)

**Strength: NOT CONFIRMED, and PROVISIONAL — do not quote as a clean result.**
`arm minus reference -0.054 +/- 0.156`, n=504, includes 0. Win rates 48.3% arm
/ 49.0% reference / 52.1% control. The aggregator REFUSED a pooled number
(4 zero-world decisions, all in `control`); the figure above is its
`--allow-problems` provisional read.

**This contrast cannot be made clean by rerunning, and that is the finding.**
The protocol failures are produced BY the thing under test. Per-side counters:

```
  label/side          searches   rejected   zero
  arm/arm   (current)    30757          2      0     0.00007  <- only current row
  arm/opp   (pre-fix)    30685        410      0
  control/arm(pre-fix)   30667        507      2
  control/opp(pre-fix)   30619        519      2
  reference/arm(pre-fix) 30609        493      0
  reference/opp(pre-fix) 30618        578      0
  ------------------------------------------------
  ALL sides                          2,509      4
  pre-fix aggregate    153,198      2,507            0.01636
  current                30,757          2            0.00007   ~252x lower
```
(Corrected 2026-08-05: an earlier version of this table omitted the `opp` side
of `control` and `reference`, so it displayed partial counts. Codex caught it;
the totals above are re-derived from the raw shards.)

The pre-fix bot layer rejects 2,507 of 153,198 sampled worlds (1.64%); the
current bot rejects 2 of 30,757 (0.007%), a ~252x lower rate, and produces no
zero-world fallbacks where the pre-fix layer produced 4. This is a DESCRIPTIVE
post-hoc screen, not preregistered and protocol-failed. So the
strict evaluator's own no-zero-world requirement is violated by `mc-prefix` BY
CONSTRUCTION. Any rerun hits the same wall; only a changed estimand escapes it.

**What this does and does not say.** It quantifies, for the first time, what the
correctness work bought: a ~250x reduction in constraint-violating world
proposals and the elimination of zero-world fallbacks, measured with both bot
layers on the SAME current engine so engine changes cancel. It does NOT show a
strength gain — the level-utility contrast includes 0. Correctness and strength
are separate axes here and only the first moved. `mc-prefix`'s ballot digest
also differs (`4d73f8cb` vs `a68f7b8b`), so this is a whole-bot-layer contrast,
not a sampler-only one.

## FINISHED — Gate 3 raw capture (not scoring)

Fresh schema-v2 capture and merge completed at 23:15 from clean compiled+strict
`836cc07`. Independent validation replayed all 768 unique rows and confirmed:

- 256 DEV / 256 CALIB / 256 REPORT;
- exactly 16 rows in every split/trick-12..19/role cell and 128/128 role
  balance per split;
- zero accepted-path sampler counters, illegal actions, engine errors or
  scored values;
- 12 rejected proposals across 9 excluded deals, with zero observed
  zero-world/impossible-world events;
- data SHA-256
  `ffccfde64932eb3a0129765f3ba903099f2e5c1da16a8287aebd0024f3456982`.

The first v1 attempt remains recoverably quarantined. Gate 3 capture is closed;
do not rerun it.

## PILOT — DEV-512 COMPLETE, SELECT NONE; CALIB/REPORT SEALED

Gate sets: `pilot_dev512.v6.json` `af78748586034f6f`, `pilot_calib512.v6.json`
`3872350f57a4dd60` (byte-unchanged, never scored).

**DEV 512/512 scored.** Eight clean shards at `884030f`, one experiment id
`a838d7415b4c2032`, bundle sha `38f61d4a9dacac6a`, aggregated exactly once with
no refusal. Codex independently reproduced both. Primary
`quota - random_fill` `+0.110 +/- 0.337` INCLUDES 0 -> **no ballot design
selected**. Aggregate retained at `runs/logs/dev512_aggregate.txt`; the seven
pre-fix shards are quarantined at `runs/logs/quarantine_prefix_75b06da/` and
were never combined.

**CALIB and REPORT remain unscored and untouched** — the contract runs CALIB on
one DEV-selected design, and there is none.

**Open:** global sampler completeness. `75b06da` is sound but necessary-only.

## FINISHED — N=30 frozen-current confirmation (seeds 102M)

**+0.222 +/- 0.140** vs N=10 over 504 preregistered fresh clusters;
arm-minus-null +0.230 +/- 0.139; null -0.008 +/- 0.154; win rates
55.2/50.9/51.2. So the `e3aeec1` result (+0.262 +/- 0.154) transfers to the
deployed executable despite sampler, ballot and decompose changes in between.
Caveat: these shards predate the `rejected_worlds` counter, so this is a
policy-as-run comparison, not proof of an exact accepted dose. Prod is live on
this (`mc-strong`, N=30, compiled engine); no redeploy without Jerry's go.

## RECENTLY FINISHED

### sampler posterior 24-state paired probe — SUPERSEDED, see the physical-
### reference block above (2026-08-05 03:10)

Kept only as a pointer. Two figures once published here are WITHDRAWN, not
merely superseded:

- the uniform-deal `+0.018 +/- 0.045` was computed over arms that shared 0 of
  24 enumerated legal sets — a sampler flag was live during state generation,
  so the "paired" statistic compared different states (Codex);
- the inference that the residual was an artifact of the flat reference is
  refuted: against the repaired physical reference the residual is 0.109 vs
  0.116, so the reference explained ~6% of it.

Current figures: weighted splits `-0.0600 +/- 0.0310`, uniform deal
`-0.0001 +/- 0.0027`, both 24/24 pairing-verified against the physical
reference. Nothing adopted; all flags OFF. (Superseded: DEV-512 has since scored 512/512 with SELECT NONE.)

### N=60 vs N=30 dose test — NO CONFIRMED ADVANTAGE, closed 2026-08-04 23:46
- Primary N=60-minus-N=30 paired utility **-0.002 +/- 0.119** over 504 fresh
  clusters; N=60-minus-null +0.004 +/- 0.129; null-minus-N=30
  **-0.006 +/- 0.134**. Every interval includes zero.
- One preregistered superiority block, no extension. This does not prove
  equivalence or saturation. The evaluator omitted rejected-world accounting,
  so interpret it as the two policies as run, not guaranteed exact accepted
  N=60/N=30 dose. Do not repeat without a materially different hypothesis and
  repaired counters.

### N=30 confirmation — CONFIRMED, closed 2026-08-04 23:40
- **+0.262 +/- 0.154** vs N=10 over 504 preregistered clusters (seeds 99M);
  arm-minus-null +0.310 +/- 0.153; null control -0.048 +/- 0.162 (includes 0).
  Independently reproduced by Codex from the raw six shards.
- **PINNED TO `e3aeec1`, NOT current main.** The action semantics and tractor
  ballot have changed since, and the manifest's ballot digest no longer matches
  source. Common-mode exposure preserves that contrast's internal validity but
  does not rule out an N-by-ballot interaction. Do NOT rerun to reinterpret the
  old result; a promotion of today's executable needs a FRESH frozen-current
  confirmation (Codex).

### action-semantics gate — CLOSED by Codex 2026-08-05 at `a2560ba`


### rewritten-sampler N=30 confirmation — CONFIRMED 23:43
- Preregistered one-block result: N=30 minus N=10 `+0.262 +/- 0.154`; N=30
  minus the true `mc-null` control `+0.310 +/- 0.153`; null minus N=10
  `-0.048 +/- 0.162`, all over 504 fresh seed clusters.
- Six equal 84-cluster shards, seeds 99,000,000-99,000,503, no extension and
  no pooling with the 96M screen. Aggregation reported no protocol problems.
- This certifies the version-pinned pre-action-fix result. Current `main` has
  since changed decomposition and the tractor ballot digest; require a fresh
  frozen-current confirmation before promoting today's executable, rather
  than reinterpreting or pooling this historical block.

### sampler certification — HISTORICAL; population claim withdrawn
- run eea78d2, clean tree. 1,600 reservoir states / 38,399 worlds, 0 invalid.
  120/120 constructed toy states fully reachable, real deal reached in all.
- Found and fixed a second sampler defect on the way: tractor run-length caps
  were never consumed. Three certifier bugs of my own also fixed.
- Later audit proved the global limit consumed only `original` rows: zero late
  rows were tested and no replay-skip counters existed. Preserve this as defect-
  finding evidence, not a closed P0 certificate. Distribution fidelity was
  never certified.


### sampler certification — 20:10, found and fixed a real defect
- 64,795 worlds across early and late ply. 12 invalid at ply>=16, all from the
  declarer pin completing a pair the cap forbade. Fixed and re-certified clean.
- Distribution fidelity explicitly NOT certified; two biases named in
  AI_POLICIES.md.

### dose contrast rerun — 19:00
- Clean aggregation, but the formal verdict is void: I passed `mc-strong` as
  `--control`, and the evaluator's control means "an arm that should NOT work".
- Measurements: N=10-N=5 +0.369 +/- 0.221; **N=30-N=10 +0.290 +/- 0.210**,
  which REOPENS the determinization question on the corrected sampler. One
  block only — needs fresh seeds and a null control.


### ballot coverage audit (dev) — 17:40, CORRECTED
- 12,340 states, 0 rebuild errors. Structured omission 51.2% leads / 0.9%
  follows. Superseded the first run's 54.0%, whose structured filter wrongly
  accepted unrelated pair throws.

### late-ply capture (Air) — 15:30
- 540,000 attempts with 0 failed draws (recorded in the v2 artifact)

### determinization screen — CLOSED negative
- N=30 vs N=10 NOT CONFIRMED (+0.101 +/- 0.150, fresh seeds). N=10 vs N=5
  PROVISIONAL (14 zero-world fallbacks; the shards' own verdict was NOT
  CONFIRMED). Block 1 was contaminated by an aborted shard; corrected.


### determinization screen — CLOSED 2026-08-04, negative
- Three blocks, 756 seed clusters. N=30 vs N=10 NOT CONFIRMED
  (+0.101 +/- 0.150 on the two confirmation blocks). N=10 vs N=5 has a strong
  secondary contrast (-0.347 +/- 0.145), but 14 zero-world fallbacks make it
  provisional under the evaluator's own protocol. Do not deploy N=30; rerun
  the dose check only after the constraint-correct sampler lands.
- Full ledger in AI_POLICIES.md.


- **ckpt_v13abs absolute-Q leaf** — NOT CONFIRMED (-0.004 +/- 0.206 paired vs
  the MC reference; v7 control +0.024 +/- 0.215). The direct paired v13-minus-
  v7 contrast is -0.028 +/- 0.185 with identical 52.8% win rates. Mis-aimed:
  trained mostly on ply<=15 `Q^H(s,a)` states and MCBot candidates, then
  deployed post-4-trick over the pinned-v1 `enumerate_actions()` ballot.

- **high-N corpus — COMPLETE** (Air, 247 min): 20,000 states x 240 shared
  worlds = 37.1M candidate evaluations, 31 MB, mean 7.7 candidates/state,
  5,283 (26%) with a best-vs-baseline gap clearing 2 SE. Synced to the mini
  with its manifest. Raw states rebuild exactly, but labels used the old
  non-strict sampler/current capped ballot and same-world maximum. This is a
  state reservoir and provisional `Q^Heuristic(s,a)` dataset, not an unbiased
  oracle, bracket target, or generic state-value target.

- **seeded Elo pool** — completed 21/21. Random-prune control ranked ABOVE the
  net-prior arm; all gaps <=28 Elo, inside the unresolved band. In AI_POLICIES.
- **race_confirm** — refuted the racing claim. Its manifest and JSONL were
  deleted by my own maintenance cleanup mid-run; only the aggregate log
  survives, so it blocks promotion but is not replayable.
- **V3 lead-ballot evaluation** — NOT CONFIRMED (+0.065 +/- 0.144 paired, the
  random-fill control higher). First claim through scripts/evaluate.py.

## STOPPED / INVALID

- **MC determinization scaling (N=30 vs N=10, N=5 control)** — INVALID. One
  of six strict shards aborted after 40 records at deal seed 93,000,146,
  flip 0, ply 46: `no worlds sampled for seat 3 (banker 3)`. The other five
  shards were terminated rather than burn compute on an aggregate that could
  no longer satisfy its preregistered contract. The public information is
  feasible (the real hidden hands provide a witness); the greedy sampler can
  consume capacity needed by constrained suits. Add this seed as a regression
  and replace the allocator with a constraint-correct sampler before rerun.
- **mini late-ply high-N corpus** — STOPPED at 617 states because it omitted
  `SHENGJI_REQUIRE_VOIDS` and `SHENGJI_STRICT_SAMPLING`. Raw states may be
  relabelled later; quarantine its N=240 labels.
- **mini high-N corpus** — DIED at 840/20,000. `nohup ... &` inside the agent
  tool does not survive its launching shell; use run_in_background.

## NOTES (mailbox — Air agent, read this)

- Every strength claim now goes through `scripts/evaluate.py`, which enforces
  its `--bar`, requires a control and SHENGJI_REQUIRE_VOIDS, and fails closed
  on a dirty tree. Do not report strength from any other path.
- The dev server on :8899 predates the LOG_DIR change and writes local test
  games into the human corpus dir. Check `logs/` each pass.
