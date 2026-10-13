# Learning and search research plan

Last reconciled: **2026-10-13** (release 45 live; new screens compare against release 45 as served).
This document owns the research architecture, the estimands, the decision tree and the planned work.
Live state is on GitHub: the board issue #707 (one row per open question; its predecessor #679 holds
everything finished through 2026-10-03), its topic issues and open PRs; fleet state is
`server/scripts/fleet_status.sh`. Policy names, deployment state and the measured ladder are in
`AI_POLICIES.md`; every screen is in Atlas v2 (`docs/atlas_v2/registry.json`) and every training run on
the scaling page (`docs/scaling_log/`). Retired lines are summarised once below and live in
`docs_archive/`.

## Objective and evidence standard

Build a Shengji policy that is demonstrably stronger than what production plays, under a
correct engine and a reproducible evaluator: beat the live policy on fresh mirrored whole games with a
single learned model that keeps improving from its own search data, and keep production's latency
tail bounded. Production is release 45 (deployed 2026-10-13 05:27 ET): the gen-5 SMV3 checkpoint
`3e89e86f`'s outcome head as one NumPy package (`smv3out-491ee4bf.npz`, served since release 36) in the
policy/value search — the policy head admits eight candidates over 64 sampled worlds, the value head
prices them, no Monte Carlo playouts — with five search rules (div, rc, tb, la, dtr), the value-guided
trump declaration (release 44) and the wide value-only bury (release 45). The exact contract is
`AI_POLICIES.md` "Production contract". The champion for every NEW strength claim is release 45 as
served (Jerry, in-session 2026-10-13: "Yes change to 45", recorded on #988 issuecomment-6142666693); confirmations keep their parent's comparator and
historical reads keep their original labels. MC-LCB is the common control inside each screen, not the
prospective comparator.

Evidence labels:

- **MECHANICS:** code, legality, parity, leakage, throughput, or rehearsal.
- **OFFLINE:** held-out prediction, calibration, stability, or teacher value.
- **SCREEN:** fresh state or whole-round evidence that selects a design.
- **CONFIRM:** pre-registered fresh mirrored evidence supporting a strength claim.
- **REJECT/SELECT NONE:** the exact registered recipe failed its bar.

The primary policy metric is paired signed level utility per round, clustered by deal seed.
Win rate, role splits, advancement tails and catastrophic losses are required diagnostics.
Offline loss, Brier score, point regret, Elo pools and human agreement never substitute for a
fresh whole-game comparison, and every strength claim goes through `scripts/evaluate.py` with
a bar.

## Operating modes (rigor tiers)

| tier | what it supports | keep | drop |
|---|---|---|---|
| **i — exploratory / DEV** | pipeline works; a model exists; a diagnostic number | score-free until sealed, reproducibility stamp (git SHA, seeds, hashes), receipts | pre-registration, confirmation machinery |
| **ii — selection screen** | choosing between designs | tier i plus a pre-registered comparison, literal parent, matched control | the tier iii machinery |
| **iii — confirmation** | a deploy or strength claim | the full immutable machinery: exact-head freeze, one-shot admission, independent reconstruction, ledger markers | — |

A lane enters tier iii only when a candidate beats the champion on a tier ii paired screen and a confirmation is
owed: Jerry's call per change (2026-10-13, in-session; recorded on #663 issuecomment-6142998363). A positive screen
can ship on his word; a fresh-seed confirmation runs when he asks or when the effect is small or borderline.

## Current program

The work queue and each lane's state are on the board issue [#707](https://github.com/jerryyyu/shengji/issues/707);
model plans and decision gates on #663; search and gameplay diagnostics on #700. Production and its rollback are
in `DEPLOY.md` "Current production".

**What would change production next:** a change that beats release 45 as served on a ten-window served-bot screen,
then the `DEPLOY.md` release checklist and Jerry's word. Confirmation is Jerry's call per change (in-session
2026-10-13, recorded on #663 issuecomment-6142998363): a positive screen can ship on his word, and a fresh-seed
confirmation runs when he asks or when the effect is small or borderline. Releases 44 and 45 shipped that way.
Correctness fixes may ship with no strength claim when the served screen is not demonstrated negative (releases 42
and 43).

**The direction (Jerry, 2026-10-11 and 2026-10-13).** "Where we use heuristics, it may be better to use the model";
after release 45, "we should keep trying in this direction." The value head already beats the heuristic at the two
decisions it took over (declaration, release 44; bury, release 45; `AI_POLICIES.md` ladder rows 13–14). The
remaining heuristic decisions are the play anchor, the heuristic first trick inside each value leaf and the
continuations the search uses.

## Planned work

Each item is a board row on #707 (row id in brackets); its state there is authoritative.

1. **Heuristic replacement, declare and bury [S15].** Screens of release 45 plus one flag, vs release 45 as served,
   the wider bury first (two-card swaps #984, merged off by default; K=128), run in parallel with the S18 screen
   (cloud and perf, both vs release 45 as served); then, in this order: declare worlds that
   score with the served bury instead of the heuristic one; declare worlds consistent with the opponents' passes,
   plus a 'wait' option; wide-bury attribution arms (K32 value-only, K64 hybrid), since release 45 changed width
   and chooser together. The paired contrast of value declare at every first-round chance vs declare-ASAP
   (v74vdefasap) is reviewed and waiting for a host. Not pursued: the policy-head first trick in the value leaf
   (`lpft`, #972; v75lpft44 inconclusive).
2. **Exact small-endgame leads [S18, #981, Codex].** An opt-in exact continuation for small endgames; fixed-root
   host qualification and the local full-round cost gate are complete. Next: a fresh paired screen vs release 45
   as served, in parallel with the S15 wider-bury screen (cloud and perf). Related Codex drafts: first-trick response search and attribution [S19/S21, #987] and structural
   lead admission [S20, #986]. The whole-hand lead admission `fla` (#973) stays off: the release-44 diagnostic
   found its admission omissions were all refused throws.
3. **C14, the grid trunk [M9].** The G1 grid trunk (`--trunk-block grid --grid-channels 44`, d3, h330),
   warm-started from GEN4-G1-SOFT-336k (checkpoint `4b829486`, the largest offline val_ce step of any
   generation and a served null in gen 4; #663 issuecomment-6130726746), on the C11 base + runPVC1–10 +
   runVD1–6 (≈ 880k shards, tag `GEN5-PROD-SOFT-allPV-plusMCLCB-880k-SMV3-C14-GRID`), with C12's settings and
   both checkpoint selections (val_ce and rank regret). Jerry 2026-10-13: "We can start training grid model now"
   and "All six (VD1–6)" (#663 issuecomment-6142998363); the launch packet is in review. Claim limit: against C12 it moves data, init
   lineage and trunk together, so a positive read is a representation swing, not an attribution. The warm start
   loads every G1 tensor, including its search head, so this is fine-tuning on the new targets. Screens: both
   selections vs release 45 as served. Width (h1024) moves to C15; C13 (C12's recipe + VD data) is parked as the
   one-variable control if attribution is wanted.
4. **True-world probe [S16] and learned belief [S17].** S16 runs the served search with the TRUE hidden hands as
   its one world (`SHENGJI_PV_ORACLE_WORLDS`, #975, merged; the screen harness only, serving refuses it) vs the
   served bot. It is a diagnostic of the current imperfect policy, not a perfect-information ceiling or a
   belief-vs-evaluation split: it keeps the finite candidate set, the evaluator and the heuristic continuation,
   and changes W64 to W1. S17, a learned belief over hidden hands that weights sampled worlds, opens only if S16
   reads large AND the read can be attributed to information rather than the W64→1 change (a sampled-world W1
   control may be needed).
5. **History encoder [M10].** The model sees per-seat counts of played cards, not play order, declaration history
   or scores (`rl/encode.py`). A sequence encoder over the trick history is a new model class: an encoder-closure
   change that needs a compatibility path for the hash-pinned package and a full re-encode. Design only, sequenced
   after S16 and C14 show where the gain is.
6. **Human-play metric [D4].** Bot win and level rate against humans in production rooms, by release, from the
   refreshed production logs. Report only when a release reaches 20 complete human rounds; refresh the log cache
   (`scripts/fetch_fly_logs.sh`) after each release.

Data: the runVD1–6 block (16k deals each, the release-44 bot as teacher) feeds C14, all six stores; runVD1–4 are
ingested, VD5–6 are next (their ingest lane is in review). The doomed-throw re-select's all-excluded fallback (it plays the throw's forced component,
which the admitted list does not contain) broke the trajectory extract until #977 recorded that play as a point
mass; completed shards were preserved and only missing clusters regenerated.

Parked or low priority (board rows): further tree/PUCT variants [S2], search beyond W64 [S6], the lookahead-teacher
corpus [M3], runSL value-only data [M5], early-round value bias [M8], the level-scale ladder benchmark [D2].

## What the scaling work taught (models)

Every row is on the scaling page with its receipt; these are the conclusions.

- **Offline loss does not order play.** The best validation CE of the programme (grid S-d4,
  0.6057) played like the leader; a 0.0376 CE gain from the v2 encoder was real in play while
  later CE gains were not. Read val_ce as calibration; the search consumes ranking.
- **Data volume inside the shortlist saturated.** 72k → 96k → 144k → 176k clusters: the last
  full doubling bought −0.0036 CE and no resolved play difference at ten windows (twelve
  proposer swaps all crossed zero).
- **Width and depth alone did not move play** (h256–h2048, d4 residual) at the shortlist
  instrument; the two-head M1 recipe (outcome + search-mean heads) was the only shortlist-era
  model to confirm on fresh deals (+0.021 [+0.004, +0.039]).
- **Encoders:** v2 was the one real gain; v3/v4/v5 bought nothing in play; v5 is closed.
- **Warm-started generations were null as packages** inside the shortlist (gen-1, gen-2,
  gen-3-warm, gen-4 run 1): the shortlist instrument ties 54–62% of deals, so the package screen
  cannot resolve small head differences.
- **The soft target is the ingredient with the largest point estimate** in the head-driven
  search (soft +0.086 vs its hard twin +0.024 on the same deals, paired +0.063 exploratory);
  no head in the W64 family is shown superior to another; a confirmation is owed.
- **Since gen 5, data and recipe changes have not moved the served read.** The five gen-5 retrains
  (`AI_POLICIES.md`), C11 and C12's three packages were inconclusive against production; deeper
  trunks (DEEP8) and the tower ladder (TOWER1) did not confirm. The open model bets are
  representation (C14's grid trunk) and inputs (M10's history encoder).
- **Corpus seeds are decks.** A screen window inside a corpus's seed range replays decks the
  trained model saw; ranges are recorded on #436 and excluded per model.

## What the search work taught

- **Model proposes, search decides** (the W32 shortlist, +0.139 on 256 rank-2 deals) was the
  first learned win; K4 beat K8; wider worlds, more final rollouts, adaptive allocation and one
  extra trick of guided depth all failed to add to it.
- **The head as the whole search** replaces playouts: the policy head admits, the value head
  prices, and it beats MC-LCB by +0.095 at W16 and +0.187 at W64 at a fraction of the cost;
  W4 loses. More worlds beyond 64 are not shown to help.
- **Policy head alone beats SmartBot after the units fix:** +0.24 vs SmartBot (arm F,
  2026-09-30; through gen 3 it was SmartBot-level); the gain does not show in served play.
- **Admission and selection rules beat tree search here** (2026-10): diversity, refusal-aware
  worlds and a points tie-break on the release-36 search were CONFIRMED in combination and
  lead-anchor on top was POSITIVE incremental (above; not a second confirmation), while PUCT on
  the same package lost (−0.417 signed levels per round vs release 36) and adaptive K16 did not
  resolve. Alone, div, rc and tb were unconfirmed or inconclusive; lead-anchor alone was positive
  exploratory, below the extension triage.
- **The value head beats the heuristic where it takes over a decision** (2026-10): the trump
  declaration (release 44, POSITIVE in first-round and later-round deals) and the bury (release 45,
  POSITIVE on first-round deals), against search-side changes that mostly did not resolve
  (adaptive worlds not confirmed, wide lead admission inconclusive, `lpft` inconclusive).
- **Terminal-level MC vs a T1 value cutoff:** the cutoff is the gain; learned continuations
  and PUCT over sampled worlds lose or add nothing at large multiples of the cost.
- **The served read is smaller than the card-play read** (+0.049 [+0.003, +0.095] served vs
  +0.086 [+0.042, +0.131] in card play, on different deals and designs). The served number is
  a common-opponent, summary-level random-effects estimate, not paired served-vs-served
  inference; own declare and bury and the opponent mix are possible explanations for the
  difference, not a measured cause. The deploy gate is the served design.

## Search and teacher strategy

1. **Candidate admission and search cost.** Keep the release-45 recipe as the reference;
   separate exact speedups from policy changes; compute-match controls when a claim is about
   cost.
2. **Depth and allocation.** Test one bounded change against the frozen release-45 control
   before any larger tree recipe; the ballot-rooted PUCT ladder is closed.
3. **Model and teacher transport.** Improve data and targets against the actual consumer (the
   search's own values as the target), preserve held-out deals, then test the resulting head in
   the same search on fresh seeds. Neither a better teacher nor better offline prediction
   guarantees this link.

Measure search work, world quality, consumer decision dose and whole-game utility separately.

## Retired lines (summary; details in the archive)

- **BELIEF R4/R5** (closed 2026-08-31): the offline Brier gain did not survive its label
  control; the DEV consumer showed no policy signal; R5 reopens only on an oracle-belief
  probe. The information contract (public facts / actor-private / beliefs / privileged labels;
  hidden-twin invariance; worlds sampled, never marginals) is retained in
  `docs_archive/BELIEF_V1_*.md` and `docs_archive/rl-plan-through-2026-08-15.md`.
- **Privileged and LLM teachers** (PT0/PT1/PT-Full, Sol/Luna): small or negative transport
  into whole-game play; Luna data retained as evidence, no active lane.
- **Global learned rankers, V11, Direct-Q, T4 widening, S4/S6 mechanisms, C0:** better label
  fit did not transport; none cleared a registered bar. Do not revive unchanged.
- **C12** (C11 base + runPVC1–10, exploration-miss weighting): three packages inconclusive vs release 42,
  closed 2026-10-12 with no demonstrated gain (#663 issuecomment-6119248471). **C13** (C12's recipe + VD data)
  is parked as C14's one-variable control.
- **Search-side flags left off** (Atlas v2 has each read): adaptive worlds (S12), wide lead admission (`wla`),
  the small-joker lead guard (S4), event-complete refusal history (S8), policy-head first trick (`lpft`).
- **The shortlist era (releases 22–28)** is condensed in `docs_archive/ai-policies-release-sections-through-r38.md`.

## Literature-derived design constraints

This is an architecture filter, not evidence that a method transfers to
four-seat partnership Shengji.

| system | useful result | Shengji constraint |
|---|---|---|
| [AlphaGo](https://storage.googleapis.com/deepmind-media/alphago/AlphaGoNaturePaper.pdf), [AlphaZero](https://arxiv.org/abs/1712.01815) | Policy focuses search, value truncates it, and improved search supplies later training targets. | Preserve the division of labor, but operate at a public-belief root. Fully observed two-player MCTS and one scalar observation value do not transfer directly. |
| [Suphx](https://arxiv.org/abs/2003.13590) | Human pretraining, distributed self-play, decision specialization, privileged-information policy curriculum, and per-hand adaptation. | Privileged scalar subtraction was not a faithful Suphx test. Separate decision surfaces and gradually remove privileged policy features if this lane reopens. |
| [DouZero](https://proceedings.mlr.press/v139/zha21a.html) | Role-specific recurrent action values learned from terminal returns at scale. | A faithful successor is from-scratch, role/action-conditioned Q with immutable actors and correct signed returns—not a warm-started oracle-residual hybrid. |
| [Libratus](https://noambrown.github.io/papers/17-Science-Superhuman.pdf), [Pluribus](https://noambrown.github.io/papers/19-Science-Superhuman.pdf), [depth-limited solving](https://arxiv.org/abs/1805.08195) | Imperfect-information search reasons over ranges and robust continuation strategies. | Keep a fixed blueprint/partner policy and test a small continuation portfolio. Poker equilibrium guarantees do not transfer to decentralized partnership play. |
| [DeepStack](https://arxiv.org/abs/1701.01724), [bridge belief Monte Carlo search](https://www.ieee-jas.com/article/doi/10.1109/JAS.2024.124488) | Maintain ranges over private hands; the bridge work supervises a belief network on true deals and samples deals from it for Monte Carlo search. | This is the closest BELIEF precedent: privileged labels, actor-visible inference, calibrated complete-world sampling, then search. Offline calibration is not strength. |
| [Bayesian Action Decoder](https://arxiv.org/abs/1811.01458) | Public actions update approximate beliefs over private information. | Feeding, withholding, joker use, failed throws, and declaration timing may inform probabilities, but require policy-shift and chronology controls. |
| [ReBeL](https://papers.nips.cc/paper/2020/hash/c61f571dbd2fb949d3fe5ae1608dd48b-Abstract.html), [Student of Games](https://arxiv.org/abs/2112.03178) | Public state plus a distribution over private states is an explicit search state. | Search a belief/range, not one determinization; two-player zero-sum convergence claims do not transfer. |
| [Meowjong](https://arxiv.org/abs/2202.12847), [Mortal](https://mortal.ekyu.moe/), [Mahjax](https://arxiv.org/abs/2605.20577) | Specialized decisions plus enormous fast-simulator experience can make simple learning recipes strong. | Treat simulator/native throughput as research leverage and specialize heterogeneous Shengji surfaces; speed cannot repair a wrong target. |
| [AutoGo](https://evjang.com/2026/04/28/autogo.html#cover) | Make the complete collect→train→evaluate loop work on a smaller domain before scaling and automation. | Rehearse the exact mechanics path at small scale, then freeze. Automation may execute a reviewed metric; it may not invent or promote one. |

## Data and artifact contract

Keep these artifact classes distinct:

1. **State reservoir:** reconstructable actor-visible state plus frozen split;
   old labels are not generic truth.
2. **Belief corpus:** actor row and separately sealed hidden-allocation target,
   with physical cross-binding and no world-generating metadata in model input.
3. **Counterfactual teacher set:** complete ballot, common worlds,
   continuation, objective, perspective, and paired outcomes—not only argmax.
4. **Episodic RL set:** immutable actor/checkpoint identity, sequential history,
   role-correct return, and retry-free provenance.
5. **Human behavior set:** replay key, pseudonymous player/deal grouping, actual
   action, source completeness, and counterfactual price before policy use.

Every dataset binds selection and split, source/engine, observation semantics,
ballot, sampler, continuation, objective/perspective, budget, producer, model,
and transitive source identity. Repeated valid sampled worlds are retained with
replacement when they represent probability mass. Invalid actor visibility,
private-kitty drift, or target cross-binding quarantines an asset regardless of
shape compatibility.

Trajectory corpora record the generating policy's identity, work and value units per store
(`policy_flags`); a corpus's deal-seed range is excluded from every screen of a model trained
on it (#436). Human data supplies policy diversity and behavioral evidence. Use all trump
ranks and player/deal-disjoint splits; do not call mixed-skill human moves an
oracle or infer true-person disjointness from mutable display names.

## Compute, review, and recovery rules

- Before authorizing a projected multi-hour run, review its complete execution
  DAG with the user. The packet must identify any repeated full-data pass and
  justify why it is not duplicate integrity work; give the worker count and
  expected utilization for every expensive node; show the exact checkpoint,
  resume, and partial-result behavior for each failure boundary; and put the
  fastest learning-bearing pilot or intermediate artifact before scale. A
  byte-integrity check is not automatically entitled to another multi-day
  recomputation.
- Profile the actual end-to-end DAG before setting caps. Admission uses measured
  pace; a conservative wall cap must not intentionally sterilize usable time.
- Long stages enforce deadlines inside their loops and publish stage, completed,
  total, percent, elapsed, ETA, worker count, and deadline headroom.
- Safe parallel stages should use available cores; GPU use must be justified by
  measured end-to-end improvement, determinism, memory, and transfer cost.
- A deadline may seal the best complete common epoch as explicitly truncated.
  Truncation is valid evidence only when it cannot masquerade as convergence.
- Durable capture/reference/index/cache/checkpoint/calibration artifacts should
  be reusable across a repaired run only when their exact contract permits it.
- Rehearsals exercise every DAG edge, refusal, reopen, and terminal route on a
  small non-scientific population. They may not tune scientific seeds,
  thresholds, architecture, or stopping behavior.
- Review the smallest consolidated source+freeze packet once. Request another
  review only after a load-bearing finding or material byte change.
- Training and calibration may inspect train/calibration splits. Test bytes
  remain closed until a durable readiness record proves every upstream artifact
  independently reopens and the terminal path has headroom.
- A missing/dirty manifest, seed-forwarding failure, hidden leakage, impossible
  world, silent short-work fallback, or unreconciled counter invalidates the
  result regardless of score.
- Use all safe cores for independent work and record the measured scaling; do not stack competing
  heavy jobs merely to report utilization. Optimize the path before scaling the population.
- Opaque multi-hour stages publish progress, active workers and ETA at least every 60 seconds.
- Material nodes are atomic, immutable, idempotently reopenable and resumable; a failure leaves a
  typed diagnostic and preserves completed work.
- Align with the user before a design adds a duplicate multi-hour reconstruction or integrity pass.
  An independent reproduction must answer a meaningfully independent question, not call the same
  implementation again.
- A deadline at any completed DAG node (collection, reconstruction, training or scoring) is graceful
  truncation, not automatic loss: seal the best valid completed boundary with an explicit truncated
  status. The common-epoch clause above is the training case of this rule.
- Seal the first interpretable scientific result before optional or independent reconstruction;
  track later verification separately, and a verifier failure must not erase valid datasets,
  checkpoints or sealed results.
- Build and exercise recovery before a one-shot opening. Recovery reuses byte-bound valid inputs and
  completed checkpoints and reruns only invalid or incomplete descendants.
- Rehearse the exact production terminal path, not just training or helper functions: a witness must
  reach the recorded output at the altitude where a regression would matter.
- Do not raise a frozen resource cap merely because the measured projection exceeds it; a cap change
  needs an independent rationale, renewed headroom analysis and explicit review.
- Prefer one optimized critical-path owner; do not keep serial and optimized copies competing for
  hosts unless the fallback has a named, still-useful role.
- Negative, incomplete, and resource-failed attempts remain in the ledger with
  their useful artifacts and explicit non-claims. Rigor must prevent cherry
  picking without erasing operational learning.

### Fleet handover and review latency

1. While a predecessor runs, maintain its next named successor on the existing
   #707 board/owning issue: priority, owner, user-authority reference, source
   and model recipe, remaining review gates, required predecessor outputs,
   host reservation and next action. A prepared successor is not ARMED.
2. Prepare those gates before the predecessor ends. If no successor is ready,
   name the exact blocker and the useful preparation that can proceed. Recheck
   current authority when a user decision changes; retire superseded budget
   or scope blockers rather than copying the previous status.
3. During an active work session, target a delta-review response within 15
   minutes when it would free a host. If that is not feasible, send an explicit
   ownership handoff and current blocker instead of silently holding the queue.
   This is a triage target, not permission to skip evidence or a background SLA.
4. For unchanged CI or a live predecessor, use one existing passive watcher
   (`gh run watch <run-id>` or cursor-neutral `agent-bus watch --actionable`)
   and work on an independent task. Record the watcher handle before yielding;
   reuse it. Observation timeout is not job failure. If persistent observation
   is unavailable, leave the pending pointer for the next real work turn.
5. At handover, verify the terminal state and usable required outputs, current
   host guards and reservation. Let an existing authorized launcher advance;
   intervene only with evidence of a stalled handover. Claude still owns
   RELEASE, and every launch retains its independent authority and review gates.
6. Spare capacity may run only named, authorized, reviewed filler. Before using
   a preemptible supervisor, test its actual stop/resume path: it owns the
   process group, stops only its own children, waits for them to exit before
   releasing the host lock, preserves completed shards, resumes without
   overwriting them, and cannot reacquire ahead of a higher-priority request.
   Exercise competing admission and stale-PID cases. If these guarantees are
   unresolved, keep the filler on HOLD and prepare the higher-priority lane;
   an idle host does not justify an unsafe launch or killing a peer job.

## Measurement rules

- Use deterministic factories and mirrored deal-seed clusters; report paired
  uncertainty over the actual randomization unit.
- Keep selection and strength separate. Sibling duels/Elo choose candidates;
  only fresh direct comparison against the named champion supports strength.
- Use common hidden worlds inside a fixed comparison and domain-separated RNG
  streams across folds.
- Select a complete multi-seed cohort by the frozen rule, never a lucky seed.
- Bind target, perspective, continuation, state distribution/horizon, ballot,
  encoder, and objective in every checkpoint.
- Report utility primary plus win rate, role splits, and signed advancement
  distribution. Do not replace the primary metric post hoc.
- A local mechanism gain must survive realistic full-round composition.
- A positive point estimate that misses its gate is a clue, not permission.
- An interval overlap is not a difference test; superiority between two arms needs a
  contrast that clears zero on a common opponent or paired deals.
- Five windows first, extend to ten only when the point exceeds +0.015 and the interval crosses
  zero. A five-window interval that spans zero is INCONCLUSIVE, reported with its MDE80; it
  supports neither "not large" nor "equal" (amendment adopted on #663). Capped (300 s) and
  uncapped screens are separate populations. Screens are 520-cluster mirrored windows. A five-window
  triage has an MDE80 of about 0.033 on the shortlist-era capped screens and about 0.05 on the
  served policy/value-search screens; each readout reports its own MDE80. Ten shared-control
  windows are a nominal read, and only fresh held-out deals confirm.
- First-round deals (the banker is decided by the declaration) and later-round deals (the banker
  is fixed) are separate populations, screened and read separately, never pooled.
- The points margin is a predeclared descriptive secondary since v66 (Jerry, 2026-10-09; #707
  board); it never overrides the level primary and is role-confounded when an arm changes who
  banks.

## Archive boundary

Closed lanes live in `docs_archive/` and the tag `archive/code-lanes-pre-cleanup-20260905`.
Update this file when the architecture, estimand, live decision tree or planned work changes.
