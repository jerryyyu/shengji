# Full-data belief in W32: fresh DEV gameplay

Jerry authorized plugging the completed #334 full-data model into legal-world
weighting and comparing against W32. No production change or new training.

## Fixed comparison

- 260 fresh independent deals, 20 per trump rank (2 through A), with 52 each
  for initial banker 0/1/2/3/undeclared. Trump suit follows the normal declaration
  process, including natural no-trump outcomes; it is not fixed by the runner.
- One ordinary-W32 round and two team-side mirrors each for uniform-pool and
  learned-pool W32: 1,300 rounds total. Mirrors are clustered by original deal
  for paired intervals, not counted as independent samples.
- Same value checkpoint as the earlier ownership gameplay screen:
  `selected-3cd27716-compact.npz`, SHA
  `fd6bb4114eb1f2ff049a77989cbd99eb35b949eef944dd72de448ff25b4fabd9`.
- Belief checkpoint: #334's selected epoch-20 `model-full/best.pt`, trained on
  92,371 eligible deals. Actual checkpoint SHA and embedded recipe binding are
  recorded at launch. Planned deck keys are checked against every deal in that
  recipe and against the earlier 14-deal screen before play begins.
- Ordinary uses the corrected legal sampler directly. Both pooled arms build
  the same 128-world proposal at a given state; uniform uses equal weights,
  learned uses the small model's count probabilities and existing bounded
  marginal fitting (500 iterations, max weight 4/N, ESS >= N/2). The mixture is
  an approximate posterior over a finite pool, not an exact joint posterior.
- Ranking/selection/report all use the chosen play sampler. W32 remains at
  32 ranking worlds, four alternatives plus incumbent, 30 selection worlds and
  300 report worlds. Rollout, declaration and hybrid bury policies are unchanged.
- Ordinary and learned arms share policy seeds within each deal. Primary
  readout: signed-level gain versus ordinary; learned-minus-uniform isolates
  weighting from finite-pool effects. Also report wins, CPU/wall, sampling
  diversity, invalid proposals, failed fits and runtime failures honestly.

## Size, execution, recovery

Fixed 260-deal DEV screen; no optional outcome stopping, checkpoint selection
or enlargement from interim scores. Based on the previous 14-deal variance,
rough MDE80 is 0.10 signed levels/round (0.434 * sqrt(14/260)). This is not
powered to confirm a 0.036-level effect or a deployment claim. A near-zero
estimate with wide intervals remains inconclusive, not proof belief cannot help.

Mini: four single-thread CPU workers, no MPS use. Both cloud hosts have ongoing
data generation and remain untouched. Mini's existing peer MPS training is
preserved. Initial estimate is roughly six hours from prior ~64-second rounds;
actual host contention and scheduling tails are reported through live progress.

Reuse the existing worker, sampler and failure-draining scheduler. Every arm
is atomically saved; completed clusters publish percent and ETA. A failed task
stops new admission and drains already-running tasks. Resume the identical
command to retain completed arms/clusters; source/checkpoint/config drift
refuses mixing. No duplicate full gameplay replay for integrity.

78 focused tests pass: all previous belief/sampler tests plus configured 260-
deal rank balance and legal preparation, actual cluster-worker mirror/seed
wiring without R4, exact saved-arm reuse and mutation refusal, paired uniform
contrast arithmetic, real-deck overlap refusal and missing-mirror refusal.

Artifacts: `~/shengji-archive/2026-09-11/simple-belief-full-w32/`.
Log: `~/shengji-archive/2026-09-11/simple-belief-full-w32.log`.
Source branch: `codex/full-belief-w32-screen`, stacked on #334.
Status: source validated; launch/results pending.
