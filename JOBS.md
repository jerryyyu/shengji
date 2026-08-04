# Fleet job ledger — mini (this machine)

The Air keeps its own at `~/Projects/shengji-compute/JOBS.md`, which is also
the inter-agent mailbox. Keep one authoritative running section here.

## RUNNING

None. The clean 512-state lead-ballot pilot is next after its coverage baseline
is refreshed against the repaired tied-code action universe.

## RECENTLY FINISHED

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
