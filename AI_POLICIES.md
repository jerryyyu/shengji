# AI policy ledger

This file is the compact, current contract for callable bot policies and the
research conclusions that affect them. It is not a run log.

- Active order and gates: `BACKLOG.md`
- Fleet and terminal stubs: `JOBS.md`
- Current cross-agent handoff: `HANDOFF_ACTIVE.md`
- Exact external-review ledger: `HANDOFF_REVIEW.md`
- Model and research plan: `RL_PLAN.md`
- Full policy history through this compaction:
  `docs_archive/ai-policies-through-2026-08-15.md`

## Current truth — 2026-08-27

- **Production champion:** `mc-s0-report-lcb` remains the only deployed policy
  with a fresh confirmed strength gain.
- **No new strength gain was proved by the closed campaign.** T4, S4 and S6
  selected none. Pair-aware continuation produced no whole-game result: Air
  timed out at `0/8` terminal shards and the checkpoint screen failed closed.
- **T4's positive control is not yet a clean widening claim.** The uninformed
  arm was work-matched to treatment, not champion, and used 14.8% more accepted
  worlds and 80.9% more searches than champion. A confirmation must separate
  candidate widening from added compute with three arms.
- **BELIEF R4 is completing offline calibration.** Trained models and reusable
  capture/reference/cache assets are sealed. Exact optimized source `d82ba224`
  is scoring calibration on Perf while exact serial source `e10cb3d` remains a
  fallback on Strength Cloud. Test is unopened. Only a reviewed readiness and
  cutover sequence may stop the fallback and open test once.
- **R5 is the efficient, recoverable successor on the same scientific question,
  not an independent replication.** Exact source `9c5928f2` is locally green
  and host-independent all-rank/human inputs are sealed. After R4 releases
  Perf, one exact-host full-DAG rehearsal, immutable freeze, and consolidated
  source+freeze review precede any run.
- **Privileged-teacher evidence now constrains the BELIEF consumer.** PT0 found
  only small late-endgame headroom; PT1 was a clean negative; PT-Full showed
  that collapsing uncertainty onto one true world is not enough; and C0's
  fixed full-information consumers all selected none. PT-Sol0 is the current
  open-DEV diagnostic of whether a bounded reasoning agent can use exact state
  and engine rollouts better. None authorizes gameplay or deployment.
- **The next model decision waits for the complete curves.** After the terminal
  reopener, compare train/calibration loss, eight-seed stability, full- versus
  half-population cohorts, human-mixture transfer and the negative control.
  Architecture, optimizer and larger-data experiments use preserved
  train/calibration artifacts; they do not reopen or tune on the sealed test.
- **Performance is enabling evidence, not strength evidence.** The accepted
  native stack materially reduced rollout wall time, but runs use only exact
  reviewed bytes and percentages from different baselines are never added.

## Callable policy registry

Policies are registered in `server/shengji/ai/registry.py`. Production sets
`SHENGJI_BOT=mc-s0-report-lcb`; the source fallback remains `mc`.

| name | role | current status |
|---|---|---|
| `mc-s0-report-lcb` | Production two-stage Monte Carlo policy. N=30 nominates; R=300 fresh common worlds compare the nominee with the incumbent; a one-sided conservative LCB controls override. | **Live champion.** Fresh RLCB-C1 measured `+0.338379 +/- 0.067706` signed levels versus `mc-strong`; the matched current-policy null was flat. |
| `mc-strong` | N=30 base Monte Carlo selection without the report fold. | Rollback and experiment control; not production. |
| `mc` | N=10 determinized Monte Carlo source fallback. | Reproducible baseline and debug policy; not production. |
| `smart` | Public-memory heuristic policy with boss, void, pair/run, point and endgame rules. | Fast rollout/baseline policy. Historical `smart-v1`/`smart-v2` remain reproducible. |
| `heuristic` | Stateless rule baseline. | Fixed low-cost reference. |
| `rl` | Experimental checkpoint argmax policy. | Opt-in only; requires `SHENGJI_RL_CKPT`. No checkpoint has deployment authority. |

Experiment-only constructors such as S4 point-banking remain outside the
shared registry. A reviewed experiment arm is not a production policy.

## Canonical research outcomes

| label | question | terminal conclusion |
|---|---|---|
| **RLCB** | Does a fresh common-world report fold improve N=30 selection? | **Confirmed and deployed.** This exact two-stage rule is the named parent for challengers. |
| **T4** | Can learned global ranking or one learned trick-5+ proposal improve protected search? | **Closed for this generation.** Whole-game treatment lost its conservative contrasts. The uninformed control's positive result is confounded with more compute and needs a three-arm confirmation. |
| **S4** | Does point-aware banking inside rollouts improve whole games? | **SELECT_NONE.** The full 16,384-cluster confirmation was clean but missed efficacy; natural dose was about 0.7%. |
| **S6** | Do targeted shuai-pai/bury ballot sources earn a fresh screen? | **SELECT_NONE_FOR_FRESH_SCREEN_DESIGN.** Bury-side criteria passed, lead-side criteria failed three gates. Preserve only a labelled bury hypothesis. |
| **PAIR-ROLL** | Does exhausted-higher-pair memory improve continuations? | **No whole-game evidence.** Air timed out; checkpoint V1 failed closed. Both admissions are spent. |
| **V11 / Direct-Q / O0** | Can learned ranking, return learning or privileged curricula replace current search? | **No promotable model.** Keep bounded proposal/diagnostic assets and the evaluation chassis; any successor must change target, credit, data or model use. |
| **H0** | Are human moves useful proposals? | **No scored result.** The run exposed a candidate-geometry bug. The repair is score-free; human actions remain proposals, not truth labels. |
| **BELIEF-V1** | Can actor-visible history predict hidden ownership well enough to improve same-work search? | **Question open; R4 is in calibration and R5 is held pending R4.** V1/R3 failed operationally before a learning result. Only a valid, independently reopened offline PASS may open B3 sampler implementation review. |
| **PRIVILEGED-TEACHER** | Can an optimized full-state policy become a safe teacher for public play? | **Current fixed consumers selected none.** PT0 was small/inconclusive versus production, PT1 negative, PT-Full preserved the ensemble warning, and C0 negative. PT-Sol0 tests a materially different adaptive consumer. Never copy one true-world omniscient argmax into a runtime policy. |

`SELECT_NONE` closes the exact population, policy and promotion claim tested.
It does not erase predeclared dose, phase/role effects, disagreement states or
tail failures. Those may motivate a materially different design, never a
post-hoc promotion or retry.

## Production search contract

`mc-s0-report-lcb` is defined by all of the following, not by its short name:

1. the exact engine and policy source;
2. the root ballot and incumbent ordering;
3. the public-information sampler and its strictness mode;
4. N=30 nomination work;
5. R=300 fresh, disjoint, common-world report work;
6. the named rollout continuation;
7. signed level utility and the one-sided paired LCB rule; and
8. deterministic factory, RNG, counter and artifact identities.

Changing any item creates a challenger. It does not inherit the champion's
evidence. Wider search, a learned proposal, a new continuation, a belief
sampler and a value leaf are different estimands and should be tested
separately.

## Correctness and information boundary

- Search may use public history, the acting player's hand and sound deductions.
  Opponent hands and hidden kitty contents are training/evaluation labels only.
- Legal sampled worlds are not automatically calibrated posterior worlds.
  Constraint validity, posterior calibration and search usefulness are
  separate gates.
- Public facts such as proven voids and legal follow obligations must not be
  mixed with soft behavioral beliefs such as “this player is probably short”
  or “probably lacks a pair.”
- Privileged training may use every hand and the kitty, but public targets must
  average over compatible worlds. An all-omniscient league measures a
  capability ceiling, not a legal policy, deployable convention or strength
  claim.
- Factory seeds must reach every stochastic component. Evaluations use mirrored
  deal clusters, independent folds, exact work counters and fail-closed short/
  zero-world handling.
- Policy evidence binds ballot, sampler, continuation, encoder semantics and
  transitive source bytes. Equal tensor shape or a familiar policy name is not
  semantic identity.
- The banker-private-kitty encoder drift remains a permanent warning: assets
  generated under incompatible information boundaries are quarantined even
  when dimensions match.

## Active production knobs

Only the current load-bearing choices stay here. Historical rejected/tied
flags and their exact measurements are retained in the archive snapshot.

| knob | current value | purpose |
|---|---:|---|
| nomination worlds | `30` | Strong base selection before the report guard. |
| report worlds | `300` | Fresh common-world comparison of incumbent and nominee. |
| base override margin | `5.0` points/round | Protects SmartBot's incumbent from noisy early rollout estimates. |
| maximum root candidates | `8` in the base contract | Bounds search work; experiment ballots must bind their own vector. |
| tractor lock | on | Keeps the heuristic tractor lead final in the production parent. |
| point-shy epsilon | `2.0` | Breaks near-ties toward risking fewer immediate points. |
| strict confirming voids | required | Confirming evidence may not use the final void-relaxing retry. |
| guarded report override | positive one-sided LCB | A point estimate alone never overrides production. |

SmartBot's adopted public-memory behavior includes safe throws, control leads,
late trump pairs, shortest-suit voiding, tempo guard, endgame control,
trump-gated/void-oriented bury, eager declaration and ruff-safe tractor rules.
These remain heuristics, not proof of optimal play.

## Evaluation and promotion rules

1. Name the exact champion, challenger and matched null.
2. Measure screens on fresh paired deal clusters; report signed level utility,
   uncertainty, role splits, win rate and tails.
3. Treat pool Elo, human agreement, offline regret and small blocks as
   selection/diagnosis only.
4. Predeclare natural dose, conditional edge, implied whole-game effect, MDE,
   maximum compute and the decision the result unlocks.
5. Keep proposal, continuation, value, allocation and report-guard changes
   separate until each earns its own evidence.
6. Use whole multi-seed cohorts; never promote a lucky seed.
7. Invalid provenance, dirty inputs, missing work, silent fallback or outcome-
   aware retry voids the claim regardless of score.
8. Deployment requires a fresh direct comparison with the named live champion.
   Performance parity and throughput gains do not substitute.

## Usage

```bash
SHENGJI_BOT=smart uv run shengji-server
uv run python -m shengji.ai.tournament
```

Programmatic factories should pass deterministic seeds explicitly. Use
`scripts/evaluate.py` for strength claims; `play_pairing`, Elo pools and human
agreement tools remain exploratory instruments.

## Archive boundary

The pre-compaction ledger, including every historical toggle, exact artifact
hash and long experiment narrative, is preserved byte-for-byte at
`docs_archive/ai-policies-through-2026-08-15.md`. Dated operational chronology
lives under `docs_archive/` and `server/runs/`. Update this file only when a
current callable policy or durable conclusion changes.
