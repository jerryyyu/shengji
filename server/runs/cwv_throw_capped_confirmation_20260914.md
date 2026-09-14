# Proposed fixed-sample throw-component confirmation

Follow-up to #389 / #390. Preparation only; no job or competing waiter installed.

Jerry's updated goal calls for this fixed1,024-pair confirmation. Existing four
uncapped windows contain 256 paired deals, mean +0.04296875 signed levels/round,
95% deal-cluster bootstrap interval [-0.025390625, +0.111328125]. This remains
promising but inconclusive. The treatment admits distinct direct components of
multi-component leads into MC; it does not impose a failed-throw penalty.

## Proposed comparison

- 1,024 **fresh** paired deals, four windows of 256, fixed before outcomes.
- Proposed seed starts 200260914, 201260914, 202260914, 203260914; verify against
  the actual launch inventory before sealing. Each window uses seed0+cluster.
- Throw-component admission alone versus flat W32. Same fd6 checkpoint,
  hybrid bury, root32/selection30/report300, static evaluator and successor reuse.
- Total play deadline300 seconds on both arms. No wide-tail or corrected-rollout
  combination in this confirmation. Capped result is separate from historical
  uncapped results; do not pool the 256 old deals into its primary estimate.
- Existing paired screen harness, at most16 workers on Perf after coordination.
  Existing corrected-rollout, Claude capped-control, and wide-tail commitments
  are preserved; no automatic race for an idle host.
- Preserve pair shards and configuration. An interrupted window is incomplete,
  not a license to replace unfavorable or slow deals. Proposed outer bound is
  four hours per256-pair window (sixteen hours maximum total), stopping the queue
  on error or timeout. This is a safety ceiling, not an ETA or a guarantee that
  every pair completes. No automatic retry or escalation of the time bound.

## Analysis fixed before launch

Primary: mean signed levels/round, bootstrap10,000 resamples of whole paired
deals, seed20260904. Publish all four windows and the pooled1,024 estimate.
No significance-triggered early stopping or outcome-driven sample extension.
Missing pairs are reported, never silently omitted from a claimed full result.
Also report win rate, per-side cap incidence/phase, failed throws, added direct
components, changed decisions, model/rollout work, total wall and latency tails.

At unchanged variance,1,024 fresh pairs gives roughly +/-0.034 CI half-width.
That is a precision projection, not assurance of significance: the true effect
may be smaller, and the cap can change policy behavior. A separate controlled
combination experiment remains eligible regardless of this point estimate, but
must retain individual-component controls.

Before launch: verify source PASS for throw+cap wiring, unchanged baseline/bury,
exact checkpoint, fresh population, available fleet lane, and explicit runtime
bound. No deployment or new infrastructure required.

Implementation ports the four reviewed #390 files onto current main with the
merged #400 deadline wrapper retained. The only conflict resolution in the
existing policy integration is to retain decision_deadline alongside the two
throw/bury recipe keys. Additional tests bind the CLI configuration and actual
deadline child factory to the throw arm and matching hybrid baseline.
