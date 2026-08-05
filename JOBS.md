# Fleet job ledger — mini (this machine)

The Air keeps its own at `~/Projects/shengji-compute/JOBS.md`, which is also
the inter-agent mailbox. Keep one authoritative running section here.

## RUNNING

None. A process check at 22:32 EDT found no capture, pilot, evaluator, duel or
simulation worker.

## READY — Gate 3 raw capture (not scoring)

The first eight-shard attempt from `8a6c2af` is closed unsuccessful: shards
1/2/3/5 completed 96 rows each, while 0/4/6/7 stopped with 51/83/30/68 partial
rows. The known witness seed `92000381` deterministically reports two
`rejected_worlds`, zero zero-world decisions and zero impossible worlds. No
merge or scoring occurred. All twelve v1 files are preserved under
`rl_data/quarantine/deep_leads_v1_8a6c2af_abort_20260804_2235/`; their
v1 manifests and source/git identity must not be mixed into the v2 relaunch.

Schema v2 makes the preregistered rejection policy executable: a safely
rejected strict world excludes the whole deal and is recorded in both observed
counters and `sampler_rejected_deals`; it is never admitted as an artifact
trajectory. A zero-world fallback or impossible-world use still aborts.
Validation is closed: 17 targeted capture tests passed; the full pure and
compiled suites independently passed **253 tests (2 skipped)**; and two clean
compiled eight-shard capture+merge smokes at `db20b7a` were byte-identical:
row `b16bc0135f3f0dd94fa46b31bdfb7f6286b55da24e33ee9b4cc28ab6157f17a5`,
manifest `88713abf7599cb318effa27dba1586e95030ef8d901018b9271ae2069e34f146`,
split `1e58ed847408b121f189d7d719bd516836c1fc6782699f24ed227c1721f9aa10`.
**Fresh v2 raw capture is GO.** Pilot scoring remains 0/512 until merge and
state freeze finish.

Every worker must use the same clean pushed commit and one distinct `I` in
0..7:

Before spending compute, compare `git rev-parse HEAD` and the complete JSON
printed by this command on Mini and Air; both must be byte-identical. In
particular, separately built Cython binaries can have different digests even
when their source agrees, and merge intentionally refuses that drift.

```bash
cd server
SHENGJI_FAST=1 uv run python -c \
  'import json; from scripts.capture_deep_leads import source_digests; from shengji.ai.registry import make_bot; from shengji.engine.ballot import mc_ballot; print(json.dumps({"sources": source_digests(), "ballot": str(mc_ballot(make_bot("mc-strong", seed=1)))}, sort_keys=True))'
```

Only after that preflight matches:

```bash
cd server
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 uv run python \
  scripts/capture_deep_leads.py capture \
  --shard-count 8 --shard-index I --max-seeds 60000 \
  --out rl_data/deep_leads.v1.jsonl
```

Suggested allocation: Mini I=0..3, Air I=4..7. Shards own disjoint pre-play
`(split,trick)` groups, so no deal is simulated by more than one worker; this
replaced correct-but-wasteful residue sharding that would have over-captured
every cell once per worker. Copy all eight shard JSONLs and manifests to one
clean checkout, then run:

If Air is asleep/unreachable, do not leave the gate idle: the Mini reports 10
logical CPUs and may run all I=0..7. Machine placement is not part of state
selection. Conversely, do not add Air midway until its full source/ballot JSON
matches Mini; a mismatched shard is guaranteed merge refusal.

```bash
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 uv run python \
  scripts/capture_deep_leads.py merge \
  --shard-count 8 --max-seeds 60000 \
  --out rl_data/deep_leads.v1.jsonl
```

Merge is the gate: it must replay all 768 rows, prove 16 rows in every cell,
verify one git/ballot/source/config, zero accepted-trajectory sampler counters,
zero errors/values, and internally consistent observed rejection/deal counts.
It must atomically emit `deep_leads.v1.jsonl`, its manifest, and
`deep_lead_split.v1.json`. A fatal shard or merge refusal is a failed job, not
permission to loosen a counter, ceiling, or cell.

## PILOT — steps 1-4 built, SCORING AT 0/512 (Codex hold)

Artifact ledger: `server/rl_data/PILOT_ARTIFACTS.md`. Current DEV engineering
set is **v3**; v1 and v2 are superseded and restored to their frozen bytes.

**v3 is NOT the gate set.** 255 early / 254 mid / 3 late by trick index, and
199/313 attacker/defender. Only 3 DEV deals supply a late lead state, so a
balanced broad-lead gate is not constructible from this corpus. Codex chose
option (b): capture deep LEAD states as a new job, then freeze distinct DEV and
CALIB artifacts.

The former runner/ballot blockers are closed in code. A clean v3 engineering
smoke ran twice in independent processes and produced the identical SHA-256
`a926cbb013fb54188a81017394b87bf23d78f8486173603c9165fe772b3f46f1`;
both copies passed the strict aggregator. Those eight descriptive states are
not evidence and are not part of the 512-state result. The remaining blocker
is the balanced deep reservoir plus newly frozen DEV/CALIB state artifacts.

## RECENTLY FINISHED

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

### sampler certification — P0 gate MET (validity + completeness) 21:40
- run eea78d2, clean tree. 1,600 reservoir states / 38,399 worlds, 0 invalid.
  120/120 constructed toy states fully reachable, real deal reached in all.
- Found and fixed a second sampler defect on the way: tractor run-length caps
  were never consumed. Three certifier bugs of my own also fixed.
- Distribution fidelity still NOT certified.


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
- 12,000 states, 105.2m. Pulled to rl_data/highn_late_air.jsonl.

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
