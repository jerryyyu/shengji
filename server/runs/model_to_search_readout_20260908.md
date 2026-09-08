# Selected-model search investigation — September 8

Baseline: A+C+D+E+F2 v2 checkpoint `3cd27716`. Keep evidence about
mechanics, prediction, gameplay and engineering cost separate.

## What is supported

| Goal | Evidence and decision |
| --- | --- |
| Selected model on Fly | PR313 qualified compact package `fd6bb411` against the selected Torch checkpoint. PR316 records the authorized all-user switch. Live health/config rechecked: selected W32, release20 image `b8f48f41`, shared 1 CPU /512MiB, one model worker, BLAS1; MC-LCB rollback preserved. |
| Policy head outside PUCT | PR317 completed value-plus-prior nominations versus value-only W32, with a width-only control. No demonstrated gain; keep the existing value-only shortlist. This tests the available old run-C public prior, not every possible future prior. |
| Better continuations | PR302 completed selected-model T1 points-leaf gameplay comparisons without a demonstrated gain. PR319's fixed 52-deal follow-up reversed its favorable 13-deal pilot: learned report guidance lost to flat W32 at higher cost. Do not scale this recipe; keep flat W32 in production. |
| Shared serving/generation optimization | PR313 removed unnecessary training exposure metadata from compact inference artifacts; exact learned arrays retained. Actual trajectory-runner backend A/B supports Torch for cloud throughput and compact NumPy for Fly memory, not a blanket NumPy speed claim. Existing shared static encoding, successor reuse and immutable weight sharing remain enabled. |
| Isolated v3 feature | PR318 implemented the next-actor cursor with legacy compatibility, then trained matched v2/v3 models on 768 baseline-fit deals. The ablation did not show a useful ranking benefit; no broad retrain or production replacement. |

## Prior nominations: complete small-DEV comparison

Each comparison contains 26 opened deals /52 mirrored rounds across 13 ranks.
U4+2 unions four value nominations with two public-prior nominations;
V4/V6 use value nominations only (plus the existing incumbent).

| Direct head-to-head | Signed levels/round | 95% deal-bootstrap interval |
| --- | ---: | --- |
| U4+2 vs V4 | -0.1346 | [-0.3654,+0.0769] |
| V6 vs V4 | 0.0000 | [-0.1923,+0.1923] |
| U4+2 vs V6 | -0.1731 | [-0.3846,+0.0192] |

All intervals cross zero. This is no demonstrated gain, not proof of harm,
equivalence, or a general failure of policy priors. U4+2 actually added
1,544/1,547 prior candidates and played 69/65 prior-origin moves in the two
comparisons. These are usage counts, not good-move labels.

The wide-ballot float32-softmax failure was repaired in PR317. Each prior arm
retains 21 original pairs unchanged and completes five under repaired source,
with explicit source-transition provenance. Original failures remain retained.
The direct pairwise payoffs are not algebraically transitive: changing the
opponent changes the game. Their differences are not measurements of replay
noise and must not be used as such to size future screens.

## Continuations: distinguish prior work from the new test

PR302's selected-checkpoint T1 points leaf versus its archived flat-W32
comparison: -0.1250 [-0.3462,+0.0865] on 52 opened deals. It did not establish
a gain. Neither this result nor the lower-LR checkpoint's inconclusive result
closes the general learned-leaf direction.

Earlier PR238 already used `net_stage=report` and the same
`len(history)+K` horizon with checkpoint `650d4144`: K1 completed the current
trick, not a newly different full-trick horizon. Its 256-deal gameplay result
was -0.00586 [-0.07031,+0.05859] versus production. The new PR319 differences
are selected checkpoint, W32 root candidates, rank population and current
inference implementation; report-only targeting itself is not new.

PR319 compares learned and training-fitted stratified-prior guidance, each
against unchanged flat W32 on the same 13 opened deals. No direct
learned-versus-prior match is inferred by subtracting these payoffs. Two null
gameplay estimates would not establish that averaging destroys a first-trick
signal. That mechanism needs independent estimator/decision-quality evidence.

Both comparisons completed 13 deals /26 mirrored rounds at exact source
`dcc05a2f`, preserving the original pair and config bytes. The reopened summaries
match the retained rows, all recorded guidance counts reconcile, and no
selection-stage net plays occurred. No gameplay was rerun for verification.

| Direct comparison vs flat W32 | Signed levels/round | 95% deal interval | Interval half-width | Decision wall ratio |
| --- | ---: | --- | ---: | ---: |
| Learned report guidance | +0.15385 | [-0.03846,+0.38462] | 0.21154 | 1.873x |
| Stratified-prior guidance | -0.03846 | [-0.30769,+0.23077] | 0.26923 | 1.140x |

The learned estimate is favorable but inconclusive, not a supported production
upgrade. The contrast with the control does not by itself establish a direct
learned-versus-prior win or a mechanism. A fixed larger DEV comparison is a
reasonable next question; do not keep extending until an interval excludes
zero, and do not treat reused DEV deals as independent confirmation.

### Fixed 52-deal follow-up: completed, negative

The follow-up was specified before launch in PR319 comment5592442666:
52 deals /104 mirrored rounds per arm, seeds `[91261203,91261255)`, four
complete cycles of 13 ranks. These are already-opened DEV deals, disjoint
from this recipe's pilot, not untouched confirmation data. The new52 are
the primary readout; the pilot is not pooled into them. Source `dcc05a2f`,
model, policy and runtime config match the pilot except count and seed start.

| Direct comparison vs flat W32 | Signed levels/round | 95% deal-bootstrap interval | Decision wall ratio |
| --- | ---: | --- | ---: |
| Learned report guidance | -0.14423 | [-0.26923,-0.02885] | 2.511x |
| Stratified-prior guidance | 0.00000 | [-0.13462,+0.12524] | 1.366x |

This is adverse exploratory gameplay evidence for the tested learned-guidance
recipe, not just an efficiency failure. It reverses the pilot's direction.
Neither subtracting the two comparisons nor inspecting the control establishes
a direct learned-versus-prior win/loss or identifies the cause. In particular,
this does not prove that every learned continuation is bad or that the model's
one-step prediction quality declined. No estimator-accuracy improvement is
claimed from gameplay payoffs or sampling standard errors.

Both arms completed with no failed or missing pairs. Learned/control job walls
were 1,155.955/849.889 seconds; CPU 6,706.466/4,641.199 seconds; peak memory
3.4/3.3GiB. Six workers per arm ran concurrently on Perf; no extra jobs were
launched on the freed workers or on Strength. Decision wall ratios compare
against **flat W32**, not production MC. Cost differences from the pilot are
measured on a different deal population and must not be treated as a code change.

The learned arm made 2,331,574 guided simulated choices, evaluated 15,103,622
rows in 120,264 forwards, and used zero selection-stage net plays. Its total
rollout ratio was 0.99972. Control made 2,346,019 guided choices with no model
forwards, also with zero selection-stage net plays. Saved summaries, exact
population, unchanged recipes and recorded guidance counts were checked from
the retained rows in under a second; no games were rerun for verification.

Decision: stop this experiment at its fixed population. Do not deploy, optimize
at scale, or extend this arm until significance changes. The best-supported
recipe remains selected-model value-only W32 plus the existing heuristic MC
continuation. A future policy change needs a new, specific failure diagnosis,
not simply more worlds, a larger model or another repeat of this screen.

Completion after the retained first pair took 578.765s learned and 513.350s
prior with six workers each, peak memory 3.6/3.5GiB. Include the initial
104.194/68.265s when budgeting all execution. The largest pair took
571.597/505.921s, so the final wide-action deal dominated wall time despite
parallelism. Learned/prior guidance made 602,942/603,897 simulated choices;
the learned model evaluated 3,992,342 rows in 31,794 forwards. Rollout-count
ratios were 1.0067/0.9942, not extra report rollouts counted a second time.

## Engineering measurements

One opened deal, both mirrors, actual trajectory runner, one isolated CPU:

| Backend | Wall including load | Peak RSS | Output comparison |
| --- | ---: | ---: | --- |
| Torch | 71.205s | 658.98MiB | 116 decisions |
| Compact NumPy | 186.580s | 113.95MiB | Same 116 semantic records after removing only declared backend/identity fields |

This single fixed-order A/B favors Torch throughput (2.62x) and NumPy memory
(5.78x lower RSS). It is not universal numeric equivalence or a fleet benchmark.
Compact package size fell from 6,497,395 to 2,284,341 bytes without changing
the six learned arrays. Original training checkpoint/ledgers are retained.

For PR319, seven saved fixtures through the actual adapter took 13.770
profiled seconds on Mini. Static encoding used 5.765 cumulative seconds,
versus 1.162 in probability/model evaluation (linear kernels 0.414).
These nested profiler times must not be summed or treated as an unprofiled
speedup forecast. If guidance quality warrants optimization, investigate
encoding/reuse before assuming larger neural batches are the main lever.
No profiler-driven source change was mixed into the running comparison.

## v3 cursor ablation

Matched from-scratch v2/v3 MLP512→256 models used identical 768 baseline-fit
deals, source mix, local split and training recipe. Local-test data are not a
fresh confirmation population. Training/evaluation took 43.6s on Mini MPS;
both selected epoch10. v3 validation CE improved slightly, but local-test CE
worsened (0.85290→0.86218), and stored-ballot regret worsened slightly.

| Candidate-afterstate stratum | Decisions | v2→v3 regret | v2→v3 recall@4 |
| --- | ---: | ---: | ---: |
| Empty trick | 134 | 0.05224→0.06716 | 0.83582→0.82090 |
| Mid trick | 405 | 0.18765→0.18519 | 0.53580→0.53333 |
| All | 539 | 0.15399→0.15584 | 0.61039→0.60482 |

Labels are stored-ballot MC-mean proxies, not exhaustive W32/optimal actions.
Grouping uses actual public trick-position features, not a guessed ply index.
Seven saved actual-W32 fixtures selected the same play in six cases; that is
consumer compatibility/sensitivity evidence, not strength. No hidden gain in
the intended empty-trick stratum justifies expanding this feature now.

## Retained evidence

- Serving and backend A/B: `~/shengji-archive/2026-09-08/w32-selected-serving.zXBQED/`.
- Prior completion: `~/shengji-archive/2026-09-08/prior-union-recovery/`;
  width control in `prior-union-screen/value6-v4/`.
- Cursor models/caches/readouts: `~/shengji-archive/2026-09-08/v3-fit768-82ttx4dj/`.
- Report guidance: `~/shengji-archive/2026-09-08/w32-report-continuation/`;
  retained output `/opt/w32-report-continuation.fEneW0/` on Perf. Pilot and
  `learned-follow52` / `prior-follow52` remain separate; `readout_follow52.py`
  produces `readout-follow52.json` without gameplay.

No production authority is implied for any experimental policy or v3 model.
