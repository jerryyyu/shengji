# First double-shortlist strength probe

26 fresh deal clusters, two mirrors each, ranks `2,3,4,5,6,7,8,9,10,J,Q,K,A`
cycled twice. The three comparisons intentionally share these 26 deals; they
are **not 78 independent games**. Reserved span `[91261164,91261190)` is
disjoint from canonical registry windows and Run F's live
`[55260904,55268904)` trajectory allocation. No game has opened at preparation.

Source: reviewed `87552e9649627de002201d5a9c480c15beb57e18` (#266), building
on #264/#265. No further policy delta. Exact execution source and native
identities are retained by each run. ABC checkpoint SHA
`3f00500c5bf207e51d50ccd59a7b78c4f917b0a8adf3f39b31e660f81baa84ec`.

## Arms, interpretation and cost

1. Learned inner ranking vs flat W32.
2. Uniform inner selection vs flat W32.
3. Flat W32 vs production `mc-s0-report-lcb` for population context.

All learned roots use exhaustive ranking with W32, incumbent + four
alternatives, production N30/R300 MC-LCB verification, static MLP encoding
and exact successor reuse. Both inner arms guide 4/30 of each selection and
report world's population, rounded up, for one additional trick; they keep
the incumbent plus four inner alternatives and the same terminal heuristic
finalist comparison. Uniform skips learned inner ranking, so work is NOT
matched. Per-world privileged continuation is a simulation approximation,
not an executable actor policy. Common max-of-five estimator structure does
not prove equal maximization-bias magnitude.

Report each arm's mean signed levels and win rate against its actual named
opponent, with paired-deal bootstrap intervals (both mirrors stay together).
The primary inner-ranking contrast is learned-minus-uniform, matched by deal
against their common flat-W32 opponent. It is not a direct learned-vs-uniform
duel. Report all arms, actual work/wall, failures and rank/suit/NT coverage;
no per-rank claim or automatic scale-up from this small screen.

## Execution and recovery

One arm at a time on Strength, Run F remains preserved and paused by its
owner. Initial learned concurrency is eight one-thread workers on the
16-core/32-GiB host, leaving memory headroom for wide legal sets; the cheaper
uniform and flat arms can use sixteen. This is a memory precaution, not an
equal-cost rule. Use 27 GiB aggregate memory protection and a two-hour
operational stop per arm. These are safety bounds, not convergence criteria.

Reuse the existing screen's 30-second progress reports and per-completed-pair
shards. If interrupted, preserve all evidence and resume only missing pairs
at the identical recipe; do not replace slow or losing seeds. A partial
population remains explicitly incomplete and potentially rank-imbalanced.
Do not overlap wall benchmarks with these runs, reopen previous frozen tests,
launch provider calls, or modify any production job.

Commands use `python -B -m shengji.train.cwv_shortlist_screen` with
`SHENGJI_FAST=1`, verified native activation, `SHENGJI_REQUIRE_VOIDS=1`, and
one numerical thread. Common flags: `--arm learned --checkpoint <ABC>
--worlds 32 --selection-worlds 30 --alternatives 4 --report-worlds 300
--encoding mlp-static --reuse-successors --clusters 26 --seed0 91261164
--trump-ranks 2,3,4,5,6,7,8,9,10,J,Q,K,A`.
Inner arms add `--baseline flat-shortlist --inner-mode learned|uniform
--inner-worlds 4 --inner-batch-size 128 --inner-reuse-successors`; the flat
context arm has no inner flags and uses the production baseline.
