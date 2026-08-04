# Fleet job ledger — mini (this machine)

The Air keeps its own at `~/Projects/shengji-compute/JOBS.md`, which is also
the inter-agent mailbox. Keep one authoritative running section here.

## RUNNING

### mini / LATE-PLY high-N corpus — launched 2026-08-04 14:25
- `SHENGJI_MIN_PLY=16 highn_build.py 12000 240 95000000 rl_data/highn_late_mini.jsonl`
- Seeds 95M+, disjoint from the Air's 91M+. Doubles throughput on the one
  asset we know is needed: post-4-trick states, which the first corpus lacks
  (90% at ply<=15) and which is why v13 was mis-aimed.
- Data generation, not a claim — it cannot produce a false positive.

### air / LATE-PLY high-N corpus — since 13:50
- `SHENGJI_MIN_PLY=16 highn_build.py 12000 240 91000000`
- 1,540/12,000 states (13%) at 14:25, ~117 states/min.

### mini / MC determinization scaling — preregistered, launching 2026-08-04
- Question: with latency unconstrained, does the otherwise identical N=30
  policy (`mc-strong`) beat deployed N=10 (`mc`)? N=5 (`mc-lite`) is the
  dose-response control.
- Six parallel shards of 42 seed clusters use contiguous, disjoint seeds
  93,000,000 through 93,000,251 (252 clusters / 504 mirrored rounds per arm).
  Every shard is included regardless of its interim or individual verdict.
- Primary: paired signed level utility, N=30 minus N=10, clustered by deal
  seed; preregistered bar `paired_utility > 0` with the interval excluding 0.
  N=30 minus N=5 is supporting attribution, not a substitute for the primary.
- `SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 SHENGJI_STRICT_SAMPLING=1`; clean
  commit, one exclusive evaluator manifest/JSONL/log per shard. Aggregate all
  six before making a claim.
- This is a current-stack production SCREEN, not the final sampler verdict:
  `pair_void` is still unenforced and must be fixed before final promotion.

## RECENTLY FINISHED (results ledgered)

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

- **mini high-N corpus** — DIED at 840/20,000. `nohup ... &` inside the agent
  tool does not survive its launching shell; use run_in_background.

## NOTES (mailbox — Air agent, read this)

- Every strength claim now goes through `scripts/evaluate.py`, which enforces
  its `--bar`, requires a control and SHENGJI_REQUIRE_VOIDS, and fails closed
  on a dirty tree. Do not report strength from any other path.
- The dev server on :8899 predates the LOG_DIR change and writes local test
  games into the human corpus dir. Check `logs/` each pass.
