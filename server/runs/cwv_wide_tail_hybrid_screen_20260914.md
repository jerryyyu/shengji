# Wide-tail launch integration

This small delta prepares #402's reviewed ranking for gameplay with the same
full-completion hybrid bury used by the throw/corrected-rollout screens.
It changes neither ranking nor bury logic. Both sides use the same checkpoint,
W32 root dose, selection/report dose and bury policy; only admission differs.
It does not claim Fly's two-second bury-budget runtime parity.

The saved stress test completed in 90.108 seconds for wide-tail while capped
W32 fell back at 300.014 seconds. That is one contended-Mini stress case, not
a population speedup or strength result. Evidence is recorded on PR #402.

The companion telemetry repair retains the full legal population when the
refinement pass is smaller. Previously the deadline phase field overwrote
379,753 with 267, although the completed shortlist receipt retained the right
count. Timing and actions are unchanged by this diagnostic repair.

## Next screen

- Fresh seed start **199260914**, 64 mirrored deal pairs, 16 workers on Perf.
- Same checkpoint on both sides: fd6bb4114eb1f2ff049a77989cbd99eb35b949eef944dd72de448ff25b4fabd9.
- `--arm learned --worlds 32 --selection-worlds 30 --report-worlds 300`
  `--alternatives 4 --batch-size 128 --encoding mlp-static --reuse-successors`
  `--wide-tail --baseline flat-shortlist --hybrid-bury --decision-deadline 300`.
- Cycle trump ranks 2 through A; use the existing deal/suit generator.
- Four-hour outer job limit, preserved completed pair shards, no automatic
  fresh-seed replacement or retry. The 300-second per-play cap applies to both
  sides and returns the existing documented fallback; it is part of the policy.
- Perf order stays: current corrected-rollout comparisons, Claude's capped
  control lane, then this screen. Verify actual host state before launching.
  This document does not install a competing waiter or launch any work.

Report paired signed levels/round with uncertainty, win rate, total runtime,
per-side cap rates and phase attribution, ranking/model work, and wide-path
frequency. Analyze naturally encountered wide positions separately; do not
select an outcome-favorable subset. Keep previous uncapped comparisons out of
this matched capped estimate. Do not infer interaction gains before testing
throw-plus-wide or other combinations against their individual components.

Before launch: consolidated delta review, saved-position coverage checks and
source/checkpoint/unused-output validation. No deployment.
