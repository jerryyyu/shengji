# Policy/value search DEV — implementation log

Tracking: #436. No production deployment or strength claim.

## First consumer

`--value-continuation 0|1|2|full --baseline flat-shortlist` replaces both
selection and the fresh independent report with final signed-level values.
`--continuation-baseline mc|full` chooses the inherited point-based MC control
or the identical heuristic continued to round end on the signed-level scale.
This extra control separates truncation from changing the payoff objective.
When a prior is supplied, it is applied to both arms. Outcome head is explicit.
The horizon counts resolved tricks from BEFORE the candidate action, not from
its afterstate. Terminal leaves use exact engine outcomes, never the model.
No accrued-points correction is added. The sampled-world SE is not a measure
of model error. No exact-endgame substitution in the new continuation arms.

### Training state class versus existing W32 consumer

The executable training bridge `cwv_data.bridge_record` calls
`value_afterstate.apply_action` (exactly one engine play), then encodes that
immediate successor. It does **not** finish the trick. Thus k0 may be mid-trick,
but it is not categorically a state class absent from this training bridge.
The existing W32 ranking consumer separately uses `finish_trick=True`; this is
the #229 consumer convention, not the training bridge convention. A four-position
real-engine bridge witness checks this distinction, with reconstruction stubbed
to isolate the real apply/encode path.

k0 remains a diagnostic immediate-afterstate probe. k1 completes the root trick;
k2 completes the next trick too. Matching an encoding/state class does not prove
calibration: sampled worlds, searched actions and continuation policies can all
shift the distribution. None of these horizons is qualified by offline CE alone.
Screen recipes and summaries explicitly state leaf class and this calibration
limitation. The first launch request is still k1 only, unchanged. This source
witness is not a retrospective audit of every historical cache shard.

## Local real-checkpoint smoke (September 15)

M1 SHA256 `3cb9cd62a083736e3b41712baabaa86398b74f0e303a4a15290ec1cd9585612d`,
MLP static encoding, outcome head, one Torch thread. State from test seed19,
first player leads first card; score the following decision. Tiny diagnostic
dose: two admission worlds, three selection worlds, two alternatives, report30,
one-trick horizon. Decision selected `S3`, accepted by engine.

- Decision wall 0.1068s (model load excluded; not a paired speed benchmark).
- 20 admission rows, 69 continuation model rows in two batches.
- 138 heuristic plies, zero terminal continuation rows/full playouts.
- 35 sampled worlds total, no rejected/failed worlds.

Focused tests cover horizon boundaries, team perspective, input preservation,
terminal bypass, finite-output refusal, real selection/report, screen factory,
recipe identity, and separation of model rows from full rollout counts.

## Still required

Deadline-child/whole-round smoke and telemetry, prior checkpoint qualification,
launch-ready source review, then fresh capped paired comparisons. PUCT with
progressive widening and batched leaves remains subsequent implementation,
not a capability provided by this first consumer. Do not interpret this small
smoke as evidence of gameplay strength or representative inference cost.

## Capped mirrored-round integration smoke

Started on Mini with one worker, seed19, two admission worlds, three selection
worlds, two alternatives, report30, mlp-static encoding. Arm k=1 versus full
heuristic signed-level control. Existing 300s supervised play deadline enabled.
Output `/private/tmp/cwv-truncated-smoke.FumMMN`; source is this uncommitted
implementation, so preserve config and do not treat it as a clean-head screen.
No production or statistical claim. Verify terminal summary before using it as
integration evidence; an unfinished pair is not success.

Completed: 1/1 paired deal (two mirrored rounds), exit0, 224.7s elapsed;
120 total decisions, zero timeouts, zero failed/rejected worlds, complete work
accounting. Arm: 3,336 learned continuation rows, 33 terminal continuations,
5,847 heuristic plies. Full control: 3,306 terminal continuations, 138,445
heuristic plies. Decision wall 109.0s versus111.8s; admission consumed107.4s
versus107.9s, so this tiny no-prior smoke is dominated by admission. Different
trajectories mean these totals are not a same-state speed comparison. One deal
does not estimate strength. Summary/config/cluster shard retained at the above
path. Executed implementation was subsequently committed as46fa5065; tests and
notes do not affect the completed worker.

Review repair: the first smoke bypassed production's sampled-hand canonical
sorting/conservation boundary and did not persist continuation details in the
wrapper trace. Preserve it as historical integration evidence, NOT as validation
of the repaired policy. The consumer now uses `_complete_determinized_hands`
and sorted kitty; wrapper saves the actual continuation trace. New tests cover
permuted sampled multisets, corrupt-world refusal and durable wrapper details.

Repaired source4153e6ce: real M1 plus priorv2
`b6d928c5a13d7de2c5267cb3e936298628998dbc3868ee13d88ce726a797d1d6`
on both sides, same diagnostic dose/seed19 and 300s cap. Completed in18.1s,
120 decisions, zero timeouts,98 persisted continuation records. Prior activated
5 times on arm and4 on control. Decision wall5.12s/7.95s; maxima0.765s/0.978s.
Evidence `/private/tmp/cwv-truncated-prior-smoke.lHJdqw`. This differs from the
old smoke in prior admission AND the correctness repair, so not an isolated
prior speedup measurement. Subsequent main integration imports reviewed #434;
revalidate separate-prior consumer tests, not repeat all historical runs.

## First bounded screen request

Fixed two comparisons, each26 fresh paired deals,13 ranks cycled twice. Arm:
M1 outcome head + priorv2, threshold10000/top256, W32/selection30/report300,
four alternatives, static encoding, successor reuse, k=1. Controls:
(a) same admission + original point-MC, (b) same admission + full heuristic
signed-level continuation. No hybrid-bury or tie-rule changes; these screens
are not directly against the deployed hybrid-bury policy. All sides have300s
play caps. Source #438 exact reviewed tip, M1/prior hashes above. Priorv2's
historical split caveat is retained; use fresh gameplay deals only.

Proposed seed start610260915 (verify disjointness against fleet run inventory
before launch). Two sequential jobs on free Perf, up to16 one-thread workers,
with disjoint output directories. Persist each pair, never overlap a peer job.
Use CLI `--value-continuation 1 --continuation-baseline mc` then `full`, plus
`--baseline flat-shortlist --worlds 32 --selection-worlds 30 --alternatives 4
--report-worlds 300 --encoding mlp-static --reuse-successors --clusters 26
--workers 16 --seed0 610260915 --trump-ranks 2,3,4,5,6,7,8,9,10,J,Q,K,A`.
Checkpoint, prior and output arguments must resolve on the target host; verify
first-consumption hashes once. No outcome-triggered extension. One2-hour job
bound per comparison; on expiry preserve completed pairs and report incomplete,
do not relaunch automatically. Initial ETA is not calibrated for this dose:
report live completion-based ETA after the first pairs, not a speculative speedup.

Readout: signed levels/round and whole-deal clustered95% interval, per-window
completeness, actual model/terminal rows and heuristic plies, decision/total wall,
tail/cap incidence and prior activation.26 pairs is a DEV screen, not proof of
non-inferiority or a shipping decision. This request must pass source review and
fleet/disjointness checks before launch. PUCT is not included in this first pair
of comparisons and stays on the active goal.

## Bounded PUCT implementation progress (not launch-qualified)

The separate `codex/policy-value-puct` branch now has a real sampled-world bot
adapter around `cwv_bounded_puct.search_worlds`. It reuses the constrained sampler,
canonical world completion, checked separate/joint prior loader, exhaustive legal
enumerator, and outcome-value evaluator. Each sampled world owns its tree and
gets one simulation per sweep; leaves across worlds are batched. Progressive
widening limits evaluated children, not legal enumeration. Descendant priors see
the acting seat's sampled world; values retain root-team signed-level perspective.

Ten focused tests pass, including a live-opponent-hand permutation witness:
holding observed information and RNG fixed leaves actions, traces and evaluated
sampled hands unchanged. This does not prove information-set correctness:
descendants assume sampled hidden hands are known (strategy fusion). Root visits
are aggregated equally by world budget; Q tie-breaks are conditional on visits,
not unbiased shared-world action estimates. The factorized prior's existing
action-length bias is unchanged.

Small real-model late-game smoke: M1 + prior v2 (identities above), two sampled
worlds, four sweeps/world, depth limit four. Legal choice CK; eight simulations,
eight value rows in four batches, five prior rows, 13 enumerated actions.
Decision wall 0.0256s excluding checkpoint load. This is a functionality witness,
not representative runtime, strength evidence, or a screen launch qualification.

Screen integration now binds `bounded_puct` in config/shard resume identity;
baseline uses the same prior/value assets, ordinary shortlist admission and MC.
Tree records bypass the MC-only trace schema (no invented incumbent/report).
Work records keep simulations, learned leaves and terminal leaves separate from
heuristic rollouts. Opponent/partner selection witnesses cover root-team signs.

Paired supervised smoke: `/private/tmp/cwv-puct-paired-smoke-20260915`, seed19,
one deal/two mirrors, W2, N3/R30/K3 baseline, PUCT two sweeps/depth3, batch128,
300s total-play cap. Terminal complete, no problems, zero timeouts, 156 decisions
(78 per side). Elapsed19.5s; PUCT312 simulations =304 model rows +8 terminal
leaves,152 value batches,260 prior rows; no heuristic rollouts. All78 PUCT
decision records persisted. PUCT decision wall4.43s vs baseline10.13s at these
deliberately different tiny doses: NOT a strength or equal-work speed claim.
42 PUCT/screen/deadline tests pass. A pre-run CLI-local variable-scope error was
fixed before any game executed; no failed scientific run or partial game reused.

Independent source review: PASS after repairing four configuration boundaries:
canonical300s deadline required by CLI/factory/cluster launch, no unsupported
successor-reuse claim, explicit outcome-head validation in parent before config
publication, and summary world count derived from actual config.34 focused
PUCT/screen tests pass after repairs; earlier42 included deadline tests. These
repairs do not change gameplay in the capped smoke above.

Remaining before launch qualification: bounded full-dose packet and representative
host timing. Perf now reserved for Claude's p14; do not overlap. No PUCT fleet
run launched. #438's training-state review resolved with source PASS at68f9dafe
(canonical main ledger14:35UTC); this does not itself reserve a host.

## Shared-world leaf diagnostic

`cwv_leaf_probe.probe_root` measures k0/k1/k2 against the same worlds/actions
continued by the heuristic to terminal. The comparator is NOT optimal-play
truth. Matrices are retained; action ranking is computed after world averaging.
No confidence interval treats world/action rows as independent deals.

First local witness `/private/tmp/cwv-leaf-probe-seed19-20260915.json`: one
existing diagnostic deal, heuristic root path at plies1/25/49, first four
production-ballot actions, four shared worlds per root, M1 outcome head.
All horizons selected a comparator-best action on these three roots. Absolute
RMSE still ranges0.82–1.64 signed levels; k1 action-gap RMSE0.19/0.19/0.38.
This illustrates common value offsets versus decision ranking, not calibrated
play strength. K0 pairwise accuracy was1/3,1,1/3 on only3/4/3 strict comparator
action pairs; k1/k2 each1 on these tiny sets. No horizon selected or promoted
from this evidence. Three probe tests pass. Retain all rows, including errors.

Actual-tree follow-up: `LeafRecorder` wraps the evaluator without changing returned
scores, retaining at most32 leaves; full heuristic comparison runs AFTER search.
The invariance test checks identical PUCT choices/visits/values/counters with and
without recording. `/private/tmp/cwv-actual-puct-leaves-seed19-20260915.json`
captures32 actual M1/prior-v2 PUCT leaves (same single diagnostic deal, root ply1,
W8×4 sweeps/depth4). They span mid-trick and boundary states. Against2181 extra
heuristic continuation plies, leaf mean bias=-0.3751 and RMSE=1.1679 signed levels.
These correlated leaves from one root do NOT establish calibration or compare
search strength. The useful capability is now measuring the actual selected
leaf population, not assuming generic offline CE transfers to it. Four probe
tests pass. No screen policy/runtime source changed by this recorder.

Source reviews now both PASS in canonical main ledger: #438 at68f9dafe,
#439 at2557b958. These reviewed commits remain the proposed run sources even
as diagnostic helpers are added. Host scheduling and seed checks remain separate.

## First bounded PUCT screen request

One fixed26-pair DEV comparison, same M1 outcome/prior-v2 identities as #438.
Arm:32 sampled worlds ×8 sweeps=256 simulations per decision, depth8 plies,
PUCT c1.5, widening2*sqrt(N+1), batch128. No noise, no root temperature, no
hybrid bury, throw addition, report tie change or successor-reuse flag. Baseline:
M1+prior-v2 W32/N30/R300/four alternatives, threshold10000/top256. Thus both
sides use the same models; the new mechanism is replacing shortlist+MC with
policy-guided determinized tree search. It is not an equal-work comparison.

Reuse the prospective #438 matched deal window610260915..610260940 (13 ranks
cycled twice), only after checking canonical generation/screen seed inventories.
Overlap across the three intentionally paired DEV comparisons is desired; no
training/held-out overlap is permitted. These are not confirmation/production
promotion tests. No outcome-based extension.

Exact invocation after target paths are validated:

```
SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
PYTHONPATH=server python -m shengji.train.cwv_shortlist_screen \
  --arm learned --checkpoint MODEL --prior-checkpoint PRIOR \
  --prior-threshold 10000 --prior-top 256 --baseline flat-shortlist \
  --value-head outcome --encoding mlp-static --worlds 32 \
  --selection-worlds 30 --alternatives 4 --report-worlds 300 \
  --puct-sweeps 8 --puct-depth 8 --puct-exploration 1.5 --puct-widening 2 \
  --batch-size 128 --clusters 26 --workers 16 --seed0 610260915 \
  --trump-ranks 2,3,4,5,6,7,8,9,10,J,Q,K,A \
  --decision-deadline 300 --out FRESH_PUCT_OUTPUT
```

Requested host: Perf **after** p14 and any existing reservations, coordinated
with Claude; source/model hashes checked at first consumption. Enclosing job
deadline2h; preserve completed pair shards if exceeded, no automatic retry.
The19.5s tiny smoke is NOT a full-dose ETA. Measure actual host timing from the
first pairs and report stage/completion/worker utilization/tails, then let the
same bounded job proceed; no separate repeated capacity census. Halt on a
correctness failure, not on neutral/negative outcomes. Summarize signed levels
with whole-deal clustered uncertainty, model/prior/simulation work, wall and
tail/timeout rates. Review PASS leaves host/seed/launch guards mandatory.

## September 15 evening: first fleet results

This update supersedes the historical pending-launch notes above. M1 sources
68f9dafe (truncation) and2557b958 (PUCT) ran unchanged on Perf; all three
26-deal/52-round DEV screens completed with zero timeouts and complete work
accounting. Same seed window610260915, ranks cycled twice, prior-v2,300s cap.

| M1 arm vs matched control | Signed levels/round (95% deal-cluster CI) | Aggregate decision-wall ratio |
|---|---|---|
| K1 vs inherited MC | +0.1154 [-0.1731,+0.4038] | 0.822 |
| K1 vs full signed-level continuation | +0.0577 [-0.1923,+0.2885] | 0.796 |
| PUCT8 sweeps/depth8 vs MC | -0.6154 [-0.8269,-0.3846] | 2.032 |

G1 follow-up (same deals; control also uses G1): K1 vs inherited MC completed
22:20:10UTC at +0.0577 [-0.1543,+0.2692], wall0.893. K1 vs full signed-level
continuation completed22:24:34UTC at +0.2500 [+0.0385,+0.4808], wall0.900.
Both have zero timeouts and complete accounting. The latter is a positive
nominal DEV interval among several comparisons, not a production-MC win or
multiplicity-adjusted confirmation. G1 PUCT completed22:37:15UTC at
-0.5385 [-0.7885,-0.2885], wall1.604, zero timeouts, complete accounting;
p99 42.53s versus29.14s and max122.97s versus80.07s. All six planned screens
are now complete. Both service chains exited successfully; no retry occurred.

K1 is strength-inconclusive, not proven equivalent. Costs include different
visited positions: these are gameplay resource comparisons, not fixed-state
engineering speedups. PUCT is clearly negative in this small DEV screen;
do not scale this recipe as-is. It uses immediate model-only leaves, with no
heuristic continuation. Its305124 expanded nodes processed509246072 legal
action entries, versus454387 model leaves and24333 terminal leaves. Enumeration
is repeated across nodes/worlds; these are not distinct decision positions.

Artifacts: Perf `/root/codex-policy-value-screens-20260915`, with local archive
under `~/shengji-archive/2026-09-15/policy-value-screens/`. G1's identical
three-arm sequence started22:15:38UTC after successful M1 completion; G1 is
also used by each corresponding baseline. Thus these compare search *within*
model, not direct G1-vs-M1 gameplay. G1 full SHA:
`1bcbb47f253a7151df08749b31868a1d1608fbf3e578a2dc4d24f232b1e2e648`.

### Actual-leaf and coverage diagnostics

`/private/tmp/cwv-shared-leaves.NZGkAY/` contains probe.py, coverage.py and
six reports of each kind. Existing diagnostic deal19; heuristic path roots at
max hand sizes12/6/3, four shared sampled worlds, eight PUCT sweeps/depth8.
Both M1/G1 capture searches are rescored on their identical captured leaves.
Each comparator runs once: full heuristic play, NOT optimal-play truth.
G1 has lower RMSE at12cards; M1 at6/3cards. These are correlated rows of ONE
deal and cannot select a model or justify a phase-dependent switching policy.

At the3071-action root, M1 visits4–6 actions/world (7–15% prior mass), with
18/10/4 of32 leaves at depth1/2/3. G1 visits2–5 actions/world, reaching at most
depth5. Configured depth8 is only a ceiling. Sparse coverage is a concrete
diagnostic clue, not a demonstrated sole cause of the gameplay loss. Next
investigation should preserve a broad common-world root comparison before
adding selective depth. Pruning/capping admission is a policy change, not a
decision-preserving optimization. No new follow-up arm is queued from this
diagnostic. Both models' negative PUCT screens support rejecting this recipe,
not rejecting PUCT in general or proving a single causal explanation.

### Decision after this bounded screen set

Retain M1+prior-v2 MC as the qualified reference. K1 has a plausible cost benefit,
but the relevant MC comparisons do not establish preserved or improved strength.
Do not infer M1-vs-G1 strength from different within-model experiments, and do
not pool these matched comparisons as independent games. Likewise, the
diagnostic leaf RMSE comparator is heuristic play, not optimal play.

If pursuing another search iteration, first test root coverage on a fixed set
of saved states: retain a shared candidate set across worlds and score each
candidate on the same worlds before adaptive visits. Keep production-ballot
anchors, compare against the unchanged root comparator, and report root
regret/coverage separately from depth. This is a policy change requiring its
own bounded comparison, not a free engineering optimization. A larger PUCT
depth limit alone cannot repair an eight-visit root budget. Avoid choosing
model/horizon by phase from the single diagnostic deal above.

Final recommendation: keep the qualified M1+prior-v2 MC recipe. Retain K1 as an
experimental cost-saving candidate, not a proven strength/noninferiority win.
Do not scale or deploy the tested PUCT arm. Any next search experiment should
preserve broad common-world root comparison and isolate selective depth as one
change. G1 did not rescue this PUCT recipe; its positive full-continuation
comparison does not override its inconclusive standard-MC comparison.

The goal's bounded exploration is complete: reviewed implementations (#438,
#439), matched M1/G1 screens, real-leaf comparisons, root coverage/depth
diagnostics, retained evidence and recommendation. Source approval is separate
from strength qualification. No production deployment was performed by this
research work. Production's hybrid-bury configuration is not part of these
plain-play screens; Claude's separately authorized deployment remains separate.

## Follow-up goal: release-27 search (September 16)

Jerry reopened research with higher-budget/deeper PUCT, shared-world root
comparison, policy-guided MC continuations, and performance profiling of
production, data generation and training. The prior negative results remain
evidence; this is a new bounded experiment, not an outcome-triggered extension.

Reviewed branches #438/#439 integrated onto main bf70cb81 in isolated worktree
`/private/tmp/shengji-puct-depth-boundary`; 71 focused PUCT/leaf/truncation/screen
tests pass. No production mutation. First diagnostic ladder uses saved roots,
M1/G1, W32 and (sweeps,depth)=(8,8),(32,8),(128,8),(128,16), with 300s supervised
limits and timeout rows retained. A dedicated saved-state runner is in progress.

Before gameplay: the old CLI refuses hybrid bury with PUCT/truncation and binds
both sides to one checkpoint. It must not be described as release27 until the
control is explicitly M1 + priorv2 threshold1000/top256 + hybrid bury (including
the serving budget), independent of the arm value checkpoint. Preserve the
same bury evaluator/config across arms, not G1 bury versus M1 bury. Record
backend/serving differences; existing Torch/NumPy qualification is not a blanket
claim for arbitrary changed inference paths.

Perf is reserved by Claude for runJS1 after v22 (canonical issue436 coordination
comment). Do not use its presently idle CPU. Candidate host is shengji-cloud
only after v22's actual process/service is terminal and its lane reservation is
released. No follow-up job has launched as of this note.
