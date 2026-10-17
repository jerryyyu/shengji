# Learning and search research plan

As of 2026-10-16. Production is release 46; new screens compare against release 46 as served.

This file owns the research architecture, the estimands, the process rules for compute and measurement, and the
lessons that shape planned work. Everything else lives on its canonical surface:

| what | where |
|---|---|
| open questions, row state, next tests and bars | board issue [#1075](https://github.com/jerryyyu/shengji/issues/1075) (predecessors #707, #679, closed) |
| model plans and decision gates; search diagnostics | #663; #700 |
| production contract, measured ladder, policy names | `AI_POLICIES.md` ("Production contract", the ladder table) |
| releases, rollback, deploy checklist | `DEPLOY.md` |
| every screen | Atlas v2, `docs/atlas_v2/registry.json` |
| every training run | the scaling page, `docs/scaling_log/` |
| fleet state | `server/scripts/fleet_status.sh` |
| this plan's history and full detail | `docs_archive/rl-plan-through-2026-10-16.md` and earlier `docs_archive/rl-plan-*` files |

## Glossary

| term | meaning |
|---|---|
| **level/round** | the primary metric: paired signed level utility per round, clustered by deal seed |
| **window** | one 520-cluster mirrored screen block of fresh deal seeds |
| **MDE80** | minimum detectable effect at 80% power for that readout |
| **as served** | the full production bot path, including declare, bury and budgets |
| **comparator** | the champion a new strength claim must beat; now release 46 as served |
| **MC-LCB** | the confirmed Monte Carlo search; the common control inside each screen, not the comparator |
| **W / K** | sampled worlds per decision / candidates the policy head admits (served: W64, K8) |
| **head-driven search** | policy head admits K candidates, value head prices them over W worlds, no playouts |
| **rule tokens** | served search flags (`div`, `rc`, `tb`, `la`, `dtr`, `vd`, `bwv`, `vdef`, …); defined in `AI_POLICIES.md` |
| **D7 + X7** | exact endgame stages at ≤ 7 cards: lead (D7) and follow (X7) |
| **belief worlds** | play worlds whose hidden hands the S17 belief model proposes |
| **first-round / later-round** | deals where the declaration decides the banker / where the banker is fixed |
| **val_ce** | offline validation cross-entropy, a checkpoint-selection signal |

## Objective and evidence standard

Build a Shengji policy demonstrably stronger than production, under a correct engine and a reproducible evaluator:
beat the served bot on fresh mirrored whole games with one learned model that keeps improving from its own search
data, with production's latency tail bounded. The standing goal is +0.05 levels/round over the served release
(Jerry 2026-10-15; board #1075).

- **Production:** release 46, deployed 2026-10-16 14:49 ET: release 45 plus the v92 combo (S17 belief worlds,
  D7 + X7, `vdef`). Release 45 (2026-10-13 05:27 ET) is the rollback. Exact contract: `AI_POLICIES.md`
  "Production contract".
- **Comparator:** new screens compare against release 46 as served (Jerry 2026-10-16, recorded on #1075).
  Confirmations keep their parent's comparator; historical reads keep their original labels. The previous
  comparator was release 45 (Jerry 2026-10-13, #988 issuecomment-6142666693).

| evidence label | supports |
|---|---|
| **MECHANICS** | code, legality, parity, leakage, throughput or rehearsal |
| **OFFLINE** | held-out prediction, calibration, stability or teacher value |
| **SCREEN** | fresh state or whole-round evidence that selects a design |
| **CONFIRM** | pre-registered fresh mirrored evidence for a strength claim |
| **REJECT/SELECT NONE** | the exact registered recipe failed its bar |

Win rate, role splits, advancement tails and catastrophic losses are required diagnostics beside the primary
metric. Offline loss, Brier score, point regret, Elo pools and human agreement never substitute for a fresh
whole-game comparison; every strength claim goes through `scripts/evaluate.py` with a bar.

## Operating modes (rigor tiers)

| tier | supports | keep | drop |
|---|---|---|---|
| **i — exploratory / DEV** | pipeline works; a model exists; a diagnostic number | score-free until sealed; reproducibility stamp (git SHA, seeds, hashes); receipts | pre-registration, confirmation machinery |
| **ii — selection screen** | choosing between designs | tier i + pre-registered comparison, literal parent, matched control | the tier iii machinery |
| **iii — confirmation** | a deploy or strength claim | exact-head freeze, one-shot admission, independent reconstruction, ledger markers | — |

A lane enters tier iii only when a candidate beats the comparator on a tier ii paired screen and a confirmation is
owed. Confirmation is Jerry's call per change (2026-10-13, #663 issuecomment-6142998363): a positive screen can
ship on his word; a fresh-seed confirmation runs when he asks or when the effect is small or borderline.

**Promotion path (tier i to tier ii)**

- **DEV duel before a screen.** An offline metric (agreement, calibration, true-world regret, coverage) does not by
  itself admit a screen. A new lever first passes a paired seat-swapped DEV duel against the served release (about
  600 deals, fresh seeds) with a bar written before it runs; only then does it get a ten-window screen. Offline gains
  have not carried: belief epoch 8's +0.83 pp agreement read +0.0062 [−0.0118, +0.0243] levels/round (v95s17e8);
  wide lead admission's 45.5% outside-K8 gap read +0.0168 [−0.0078, +0.0414] (v94wla46).
- **Strength ceiling before cost work.** A search mechanism's first gameplay test runs with its serving deadline and
  node caps lifted. Latency or approximation work starts only after a positive ceiling; a null ceiling parks the
  mechanism.
- **Combination candidate.** The largest served gain came from composing proven parts: release 46 read
  +0.2284 [+0.2046, +0.2521] vs release 45, more than its parts' sum. Keep one running combination of near-miss
  levers on the board and test it as one duel rather than each lever alone.

## Planned work

**What changes production next:** a change that beats release 46 as served on a ten-window served-bot screen,
then the `DEPLOY.md` release checklist and Jerry's word. Release 46 shipped on its screen plus a confirmation
(v92c) and a latency gate (v93lat). Correctness fixes may ship with no strength
claim when the served screen is not demonstrated negative (releases 42, 43).

**Direction (Jerry 2026-10-11, 2026-10-13):** "Where we use heuristics, it may be better to use the model";
after release 45, "we should keep trying in this direction." Heuristics still in the served bot: the play
anchor, the heuristic first trick inside each value leaf, and the continuations before the exact endgame.

The open rows below mirror board #1075; the board is authoritative for state, next test, bar, owner and host.

| area | open rows (board id: question) | parked rows |
|---|---|---|
| search | S35 belief-informed multi-trick hybrid search; S33 greedy-finished leaves; S38 paired completed-trick horizon; S32 wider lead shortlist (K=32) | S36 eight-card exact dedup; S37 failed-throw exposure |
| belief | S39 belief successors (later S17 checkpoints) | S34 capacity-aware kitty draw; S25 human-seat model; S22, S23 (propose close) |
| model | M13 C15 value model on release 45's trunk; M9 C14 epoch 11 (v88); M10 history encoder, after M13 | M12 game-state objective |
| sampler / declare | S30 model-free fallback sampler (`wu`+`kb`); S15 'wait' declare under belief | S31 (into S30); S40 later-round value declare |
| data | M17 corpus round coverage (runPVS1/2) | — |
| infra / measure | D8 comparator bank; D9 two-look screens; D11 lane overhead; D4 human-play metric | D13 SSD dropout (propose close) |

Packets built against release 45 (S32, M9, S30) are rebuilt against release 46 before queueing.

## What we learned

Each lesson summarises Atlas v2 and scaling-page rows. Superseded wording is in the archive.

### Models

| lesson | evidence | status |
|---|---|---|
| Offline loss does not order play; val_ce is calibration, search consumes ranking | grid S-d4 best val CE 0.6057 played like the leader; v2 encoder's 0.0376 CE gain was real in play, later ones not | still true |
| Checkpoint selection by val_ce can leave strength unused | C11 epoch 9 beat val-selected epoch 6: v54ep9c +0.0455 [+0.0079, +0.0831] | still true |
| Heads in the W64 family can differ resolvably | SMV3 head vs release 30: v36a2 +0.0393 [+0.0033, +0.0752], confirmed (release 36)¹ | corrected |
| Shortlist-era data volume saturated | 72k → 176k clusters: last doubling −0.0036 CE, twelve proposer swaps all crossed zero | still true (shortlist era) |
| Width and depth alone did not move play | h256–h2048, d4; DEEP8 and TOWER1 did not confirm | still true |
| Encoders: v2 was the one real gain | v3/v4/v5 bought nothing in play; v5 closed | still true |
| Soft (search-value) targets carry the largest point estimate | soft +0.086 vs hard twin +0.024 on the same deals; paired +0.063 exploratory | still true |
| Retrains since SMV3 have not beaten production | gen-5 arms, C11 e9 vs release 38 (v55e9r38 −0.0145), C12, C14 E5 (v84 −0.0133): all inconclusive | still true; open bets are C15 (M13) and history (M10) |
| Corpus seeds are decks | a window inside a corpus's seed range replays decks the model saw; ranges on #436, excluded per model | still true |

¹ The shortlist instrument tied 54–62% of deals and could not resolve head differences (warm-started generations
null as packages); the served W64 screens can. The M1 two-head recipe was the one shortlist-era confirmed model
gain, +0.021 [+0.004, +0.039].

### Search

| lesson | evidence | status |
|---|---|---|
| Model proposes, search decides | W32 shortlist +0.139 on 256 rank-2 deals; K4 beat K8 | still true |
| The heads can be the whole search | head-driven search vs MC-LCB +0.095 at W16, +0.187 at W64; W4 loses | still true |
| No resolved benefit from the tested additional-world recipes; a better world draw helped | belief worlds v86bw45 +0.1165 [+0.0914, +0.1416]; 512 vs 64 worlds −0.0007 [−0.0022, +0.0008] per decision on 2,133 replayed decisions (board #707 S2 closure) | replaces "worlds are the lever" |
| A better policy head alone does not show in served play | head alone +0.24 vs SmartBot (arm F, 2026-09-30); value head decides | still true |
| The tested admission-rule combo beat its parent; the tested PUCT recipe lost | div + rc + tb confirmed together (release 38); PUCT −0.417 vs release 36 | tested recipes only; horizon/hybrid search stays open (S35, S38) |
| Model-owned decisions and exact endgames moved the result | `vd` (release 44), `bwv` (release 45), v92 combo +0.2167 [+0.1923, +0.2412] (release 46) | still true |
| The value cutoff is the gain, not terminal MC | learned continuations and PUCT over worlds lose or add nothing at large cost | still true |
| Knowing the hidden hands is worth a lot to the current search | true-world probe v78orc45 +0.4026 [+0.3806, +0.4245]; a diagnostic, not a ceiling² | still true |
| The served read is smaller than the card-play read | +0.049 [+0.003, +0.095] served vs +0.086 [+0.042, +0.131] card play³ | still true |

² v78 keeps the candidate set, the evaluator and the heuristic continuation, and changes W64 to one true world; it
is not a perfect-information ceiling or a belief-vs-evaluation split. The soft-oracle probe v83sorc45 read +0.3093.

³ Different deals and designs; the served number is a common-opponent summary-level estimate, not paired
served-vs-served inference. Own declare/bury and the opponent mix are possible, unmeasured explanations. The
deploy gate is the served design.

## Search and teacher strategy

1. **Admission and cost.** The release-46 search is the reference. Separate exact speedups from policy changes;
   compute-match controls when a claim is about cost.
2. **Depth and allocation.** Test one bounded change against the comparator before any larger tree recipe; the
   ballot-rooted PUCT ladder is closed.
3. **Model and teacher transport.** Improve data and targets against the actual consumer (the search's own values
   as the target), preserve held-out deals, then test the head in the same search on fresh seeds. A better teacher
   or better offline prediction does not guarantee this link.
4. **Paired worlds, and the flat W64 search as the yardstick** (search audit, 2026-10-15, S33). Every search
   variant scores all candidates, and every reply inside a lookahead, on the SAME sampled worlds. Never allocate
   one world per visit (PUCT v1's −0.417). Before any screen, a search change must beat the flat W64 K8 paired
   search offline on the audit's true-deal yardstick (`search_audit_probe_v4.py` / `analyze_audit.py`, same probe
   states): sf Δ ≥ +0.003 per decision with a 95% CI above zero, and vt Δ ≥ 0, on at least 700 decisions.⁴

Measure search work, world quality, consumer decision dose and whole-game utility separately.

⁴ Why: 88% of per-leaf value variance is common to all candidates (96% before trick 8; candidate signal 6%,
interaction 5%), so an unpaired estimate is about 10× noisier per sample. Giving each candidate its own 64 of 512
worlds flips the argmax in 51% of decisions and costs +0.0158 [+0.0133, +0.0182] levels per decision; resolving
the median top-2 gap (0.0185 levels) at z = 2 takes about 11,000 unpaired visits per child against about 120
paired worlds, roughly 90×.

## Closed and retired lines

One list for retired lines, flags left off and parked successors. Atlas v2 has each read; do not revive a line
unchanged.

| line | outcome | pointer |
|---|---|---|
| BELIEF R4/R5 (closed 2026-08-31) | Brier gain failed its label control; superseded by the S17 learned belief (release 46) | `docs_archive/BELIEF_V1_*.md` |
| Privileged and LLM teachers (PT0/PT1/PT-Full, Sol/Luna) | small or negative transport to whole games; Luna data kept as evidence | archive |
| Global rankers, V11, Direct-Q, T4 widening, S4/S6 mechanisms, C0 | better label fit did not transport; no registered bar cleared | archive |
| C12 (C11 base + runPVC1–10) | three packages inconclusive vs release 42; closed 2026-10-12 | #663 issuecomment-6119248471 |
| C13 (C12 recipe + VD data) | parked as a one-variable control for C14; no board row | #663 |
| Search flags left off | adaptive worlds (S12), `wla`, small-joker guard (S4), refusal history (S8), `lpft`, `fla` | Atlas v2 |
| PUCT, root allocation, adaptive K16, W128/W256 | none cleared zero vs its parent | `AI_POLICIES.md` "Not taken" |
| Shortlist era (releases 22–28) | condensed | `docs_archive/ai-policies-release-sections-through-r38.md` |

The information contract from the BELIEF work (public facts / actor-private / beliefs / privileged labels;
hidden-twin invariance; worlds sampled, never marginals) still binds belief lanes; see
`docs_archive/rl-plan-through-2026-08-15.md`.

## Literature-derived design constraints

An architecture filter, not evidence that a method transfers to four-seat partnership Shengji. The full table, with
links and every reported number, is in `docs_archive/rl-plan-through-2026-10-16.md`.

| theme | systems | what we take |
|---|---|---|
| search with learned heads | AlphaGo, AlphaZero | policy focuses, value truncates, search supplies targets; root at a public belief |
| beliefs over hidden hands | DeepStack, bridge belief MC, ReBeL, Student of Games, BAD | search a belief, not one determinization; supervised belief, calibrated sampling |
| inference from play | GIB, Ben, Kermit, card-location and policy-based inference | weight worlds by visible history, with floors; gate on true-deal card agreement |
| strategy fusion, endgames | Frank & Basin, αμ, EPIMC, Long et al. 2010 | fix per-world minimax and continuations locally first; no transferable ceiling |
| search cost | NooK, recursive MC, ISMCTS, GO-MCTS | published per-move costs (not a benchmark on our Fly host) exceed 3 s; they are context, not a general depth limit |
| imperfect-information solving | Libratus, Pluribus, depth-limited solving | fixed blueprint plus a small continuation portfolio; no equilibrium guarantee |
| privileged training | Suphx, PerfectDou, ShengJi+, PKU Botzone | privileged critics/auxiliaries may transfer; oracle guiding failed in Sheng Ji |
| scale and specialization | DouZero, Meowjong, Mortal, Mahjax, AutoGo | throughput is leverage; rehearse the loop small; speed cannot fix a target |
| partnership and humans | DanZero(+), GuanZero, piKL, Joint Policy Search | partner/level features first; human-seat model for world weighting (D4-gated) |

## Data and artifact contract

| artifact class | must carry |
|---|---|
| state reservoir | reconstructable actor-visible state and a frozen split; old labels are not generic truth |
| belief corpus | actor row and a separately sealed hidden-allocation target, physically cross-bound; no world-generating metadata in model input |
| counterfactual teacher set | complete ballot, common worlds, continuation, objective, perspective and paired outcomes, not only argmax |
| episodic RL set | immutable actor/checkpoint identity, sequential history, role-correct return, retry-free provenance |
| human behavior set | replay key, pseudonymous player/deal grouping, actual action, source completeness, counterfactual price before policy use |

- Every dataset binds selection and split, source/engine, observation semantics, ballot, sampler, continuation,
  objective/perspective, budget, producer, model and transitive source identity.
- Repeated valid sampled worlds are kept with replacement when they represent probability mass.
- Invalid actor visibility, private-kitty drift or target cross-binding quarantines an asset, whatever its shape.
- Trajectory corpora record the generating policy's identity, work and value units per store (`policy_flags`); a
  corpus's deal-seed range is excluded from every screen of a model trained on it (#436).
- Human data supplies policy diversity and behavioral evidence: use all trump ranks and player/deal-disjoint
  splits; mixed-skill human moves are not an oracle, and mutable display names do not prove person-disjointness.

## Compute, review, and recovery rules

**Before a multi-hour run**

- Review its complete execution DAG with the user. The packet identifies any repeated full-data pass and why it is
  not duplicate integrity work; gives worker count and expected utilization for every expensive node; shows
  checkpoint, resume and partial-result behavior at each failure boundary; and puts the fastest learning-bearing
  pilot or intermediate artifact before scale.
- Align with the user before a design adds a duplicate multi-hour reconstruction or integrity pass. A byte-integrity
  check is not automatically entitled to another multi-day recomputation; an independent reproduction must answer a
  meaningfully independent question, not call the same implementation again.
- Profile the actual end-to-end DAG before setting caps. Admission uses measured pace; a conservative wall cap must
  not intentionally sterilize usable time. Do not raise a frozen cap merely because the projection exceeds it: a cap
  change needs an independent rationale, renewed headroom analysis and explicit review.
- Rehearse every DAG edge, refusal, reopen and terminal route on a small non-scientific population; rehearsals may
  not tune scientific seeds, thresholds, architecture or stopping. Rehearse the exact production terminal path: a
  witness must reach the recorded output at the altitude where a regression would matter.
- Build and exercise recovery before a one-shot opening.
- Review the smallest consolidated source+freeze packet once; request another review only after a load-bearing
  finding or material byte change.

**Resources**

- Use all safe cores for independent work and record measured scaling; do not stack competing heavy jobs merely to
  report utilization. Optimize the path before scaling the population.
- GPU use must be justified by measured end-to-end improvement, determinism, memory and transfer cost.
- Prefer one optimized critical-path owner; keep serial and optimized copies competing for hosts only when the
  fallback has a named, still-useful role.

**While running**

- Long stages enforce deadlines inside their loops and publish stage, completed, total, percent, elapsed, ETA,
  worker count and deadline headroom. Opaque multi-hour stages publish progress, active workers and ETA at least
  every 60 seconds.
- Material nodes are atomic, immutable, idempotently reopenable and resumable; a failure leaves a typed diagnostic
  and preserves completed work.
- Training and calibration may inspect train/calibration splits. Test bytes stay closed until a durable readiness
  record proves every upstream artifact independently reopens and the terminal path has headroom.

**Deadlines, failure and recovery**

- A deadline at any completed DAG node (collection, reconstruction, training or scoring) is graceful truncation,
  not automatic loss: seal the best valid completed boundary (for training, the best complete common epoch) with an
  explicit truncated status. Truncation is valid evidence only when it cannot masquerade as convergence.
- A missing/dirty manifest, seed-forwarding failure, hidden leakage, impossible world, silent short-work fallback
  or unreconciled counter invalidates the result regardless of score.
- Recovery reuses byte-bound valid inputs and completed checkpoints and reruns only invalid or incomplete
  descendants. Durable capture/reference/index/cache/checkpoint/calibration artifacts are reused across a repaired
  run only when their exact contract permits it.
- Seal the first interpretable scientific result before optional or independent reconstruction; track later
  verification separately, and a verifier failure must not erase valid datasets, checkpoints or sealed results.
- Negative, incomplete and resource-failed attempts stay in the ledger with their useful artifacts and explicit
  non-claims. Rigor must prevent cherry picking without erasing operational learning.

### Fleet handover and review latency

1. While a predecessor runs, keep its next named successor on the board (#1075) or the owning issue: priority,
   owner, user-authority reference, source and model recipe, remaining review gates, required predecessor outputs,
   host reservation and next action. A prepared successor is not ARMED.
2. Prepare those gates before the predecessor ends. If no successor is ready, name the exact blocker and the useful
   preparation that can proceed. Recheck authority when a user decision changes; retire superseded budget or scope
   blockers rather than copying the previous status.
3. During an active session, target a delta-review response within 15 minutes when it would free a host; otherwise
   send an explicit ownership handoff and current blocker instead of silently holding the queue. This is a triage
   target, not permission to skip evidence or a background SLA.
4. For unchanged CI or a live predecessor, use one existing passive watcher (`gh run watch <run-id>` or
   cursor-neutral `agent-bus watch --actionable`) and work on an independent task. Record the watcher handle before
   yielding and reuse it. An observation timeout is not job failure. Without persistent observation, leave the
   pending pointer for the next real work turn.
5. At handover, verify the terminal state, usable required outputs, current host guards and reservation. Let an
   existing authorized launcher advance; intervene only with evidence of a stalled handover. Claude still owns
   RELEASE, and every launch keeps its independent authority and review gates.
6. Spare capacity runs only named, authorized, reviewed filler. Before using a preemptible supervisor, test its real
   stop/resume path: it owns the process group, stops only its own children, waits for them to exit before releasing
   the host lock, preserves completed shards, resumes without overwriting them, and cannot reacquire ahead of a
   higher-priority request. Exercise competing admission and stale-PID cases. If any guarantee is unresolved, keep
   the filler on HOLD and prepare the higher-priority lane; an idle host does not justify an unsafe launch or
   killing a peer job.

## Measurement rules

**Design**

- Deterministic factories and mirrored deal-seed clusters; report paired uncertainty over the actual randomization
  unit.
- Common hidden worlds inside a fixed comparison; domain-separated RNG streams across folds.
- Bind target, perspective, continuation, state distribution/horizon, ballot, encoder and objective in every
  checkpoint. Select a complete multi-seed cohort by the frozen rule, never a lucky seed.
- First-round and later-round deals are separate populations, screened and read separately, never pooled.
- Capped (300 s) and uncapped screens are separate populations.

**Reading**

- Selection is not strength: sibling duels and Elo choose candidates; only a fresh direct comparison against the
  named comparator supports strength.
- Report utility primary plus win rate, role splits and signed advancement distribution; never replace the primary
  post hoc. The points margin is a predeclared descriptive secondary since v66 (Jerry 2026-10-09); it never
  overrides the level primary and is role-confounded when an arm changes who banks.
- A local mechanism gain must survive realistic full-round composition. A positive point that misses its gate is a
  clue, not permission.
- Interval overlap is not a difference test: superiority between two arms needs a contrast that clears zero on a
  common opponent or paired deals.

**Window rule (default)**

- Five windows first; extend to ten only when the point exceeds +0.015 and the interval crosses zero.
- A five-window interval spanning zero is INCONCLUSIVE, reported with its MDE80; it supports neither "not large"
  nor "equal" (amendment adopted on #663).
- Five-window MDE80 is about 0.033 on shortlist-era capped screens and about 0.05 on served head-driven screens;
  each readout reports its own. Ten shared-control windows are a nominal read; only fresh held-out deals confirm.

**Predeclared statistics options** (D9, 2026-10-15; code `server/shengji/eval/paired_window_stats.py`; adoption on
HOLD per board #1075). A lane may predeclare either or both before any outcome; otherwise it keeps the frozen
DerSimonian-Laird (DL) pool and one ten-window read. Sealed rows keep their original pooling and labels.

- **Adoption gate.** Every number is labelled *nominal* (the ideal model: known window SEs, equal information,
  no between-window variance, fixed-effect pooling) or *calibrated* (simulated through the module, SEs estimated
  from 520 clusters). A lane adopts an option only by predeclaring that it lies inside the calibration envelope⁵
  and which calibrated target applies.
- **`fe-q-gated`.** Inverse-variance pool unless Cochran's Q rejects homogeneity at p < 0.10 (Q > 14.68 on 9 df),
  then DL. Canonical lines state Q, Q/df, p, tau², the estimator that fired and the interval's calibrated coverage.
- **`two-look-obf-futility-v1`.** The launcher interleaves arms by seed and pauses after five seeds. At five
  windows: POSITIVE or NEGATIVE if |z| > 2.797; NOT AHEAD (a binding futility stop) if the point is ≤ 0; else
  continue. At ten windows: judge at |z| > 1.977. Intervals are nominal 95% repeated-confidence intervals.
- A Q below the gate is not evidence of homogeneity.
- NOT AHEAD is never "null", "equal" or "harm"; harm below the interim bound is not detected (v79's sealed NEGATIVE
  reads NOT AHEAD).
- For a lane that predeclares two-look, it replaces the five-window rule (two-sided error 0.062).
- Coverage, error, power and audit figures for both options are in `docs_archive/rl-plan-through-2026-10-16.md`.

⁵ Package or fully divergent arms, with window SEs resting on hundreds of divergent clusters and between-window SD
at most one window SE. Flag arms with mostly identical rounds are outside it.

## Archive boundary

Closed lanes live in `docs_archive/` and the tag `archive/code-lanes-pre-cleanup-20260905`. Update this file when
the architecture, estimand, process rules or a lesson changes; row state belongs on the board.
