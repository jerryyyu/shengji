# AI policy ledger

This is the authoritative synthesized ledger for callable bot policies,
policy-affecting behavior, and conclusions that survived the measurement
rules. It is deliberately **not** a notebook or live conversation.

- Active priorities and gates: `BACKLOG.md`
- Running and completed compute: `JOBS.md`
- Reviewer/Claude discussion: `HANDOFF_REVIEW.md`
- Model chronology and post-mortems: `RL_PLAN.md`
- Superseded detail: `docs_archive/`

**Structure.** Current conclusions come first, followed by callable policy and
flag definitions. The final evidence map points to archived chronology. Do not
append run logs here: update the synthesis when evidence changes a conclusion,
and put exact run detail in `JOBS.md` or the dated archive.

## Current synthesis — 2026-08-09 19:15 EDT

### Canonical terminal-results table

This is the one compact index of decision-changing AI evidence. Detailed
mechanics remain below and exact job chronology remains in `JOBS.md` and the
dated archive. Other documents should link here instead of copying a second
results table.

| date | lane | strategy, in plain English | terminal verdict | headline result | what it means |
|---|---|---|---|---|---|
| 08-07 | report-LCB / RLCB-C1 | Let N=30 MC nominate one move, recheck that move against the heuristic choice on 300 fresh shared worlds, and override only when a conservative lower bound is positive. | **CONFIRM** | `+0.338 +/- 0.068` signed levels versus `mc-strong`; matched null `-0.019 +/- 0.068` | The deployed one-round decision rule is stronger than its named N=30 parent. It does not prove adaptive allocation or multi-round progression. |
| 08-07 | formal S0 | Compare several confidence and work-allocation rules through one sealed screen/confirmation pipeline. | **SELECT NONE** | S0c outcomes remain unread | The evidence chain failed before the corrected evaluator parsed scores. Never retry, pool or infer a numerical result. This does not undo independent RLCB-C1. |
| 08-05 | DEV-512 lead ballot | Offer more context-specific lead combinations, model-ranked choices, or matched random choices, then ask whether the wider ballot contains better moves at equal work. | **SELECT NONE** | quota-minus-random `+0.110 +/- 0.337`; incumbent had the lowest equal-work regret | The registered widening/selectors did not earn CALIB or a duel. It does not reject all proposal search. |
| 08-07 | V11 direct-v2 | Use the learned V11 pairwise model to choose or propose a move while retaining the current policy as a protected fallback. | **SELECT NONE** | v11-minus-current `-0.141 +/- 0.070`; v11-minus-null `-0.110 +/- 0.070` | No direct or protected-anchor composition. V11 survives only as a proposal/ranking and teacher diagnostic hypothesis. |
| 08-07 | Direct-Q 144M | Train an action-conditioned value model directly from played-game returns and let its predicted return choose actions. | **SELECT NONE** | gameplay `+0.163 +/- 0.059`, but seed 1 and both pooled role held-out MSE gates failed | The attractive gameplay tail cannot override the registered learning failure. Redesign rather than extend. |
| 08-08 | Suphx O0 | Give a training-time oracle all hands and test whether its privileged signal can teach a public-information policy something useful. | **SELECT NONE** | oracle-minus-public `+0.073`, LCB `+0.0025`; seed means `+0.344/-0.207/+0.082` | Full information produced an aggregate signal but not robust seedwise benefit. O1 is unauthorized. |
| 08-09 | Suphx O0-v2 | Repeat the oracle/public comparison on identical public trajectories and separately test whether emphasizing larger oracle margins helps. | **SELECT NONE** | CRN control oracle-minus-public `+0.015`, LCB `-0.067`; plus-margin `-0.047`, LCB `-0.109`; interaction `-0.062` | Shared-public CRN repaired the comparison mechanics but did not make oracle use robust. Margin sharpening was directionally worse, no cell advanced, and O1 remains unauthorized. |
| 08-08 | Teacher-v3 Stage B / audit-v2 | Compare cheap heuristic-continuation labels with much deeper MC-continuation labels on ordinary states to see whether cheap labels are trustworthy. | **STAGE B PASS / AUDIT OPERATIONAL REFUSAL** | cheap-minus-gold regret upper bound `0.0195 < 0.10`; audit shard 6 stopped on an incomplete champion-report continuation and published no labels/gate | Cheap labels agreed on sampled ordinary states. The continuation audit produced no ML verdict and is nonretryable; reviewed score-free diagnostics now gate a fresh versioned synthetic contract. |
| 08-09 | Teacher-v3 fresh champion audit | Repeat that label-fidelity comparison on an untouched 64-state complement and identify where ordinary N=30 labels become uncertain enough to need expensive treatment. | **PASS / STAGE-C DESIGN** | cheap-choice all-64 regret upper bound `0.0354`; N=30-choice upper bound `0.0439`, both below `0.10`; N=30 boundary-8 diagnostic upper bound `0.1421` | The cheap and N=30 choices are champion-faithful on the frozen 64-state complement. The boundary diagnostic motivates hard-tail escalation. Reviewed adapter `56ccefbd…c2442` now freezes that design-only contract; it authorizes no labels, training or promotion. |
| 08-09 | Teacher Stage-C design v3 | Turn the audit lesson into one finite recipe: keep broad cheap ordinary anchors, spend deeper disjoint root comparisons on hard cases, and conditionally add supported human/model/mechanism proposals without recursively calling MC inside MC. | **SCORE-FREE FROZEN / REVIEW OPEN** | source `20bdb95`; packet `f213314a…3b4`; 1,024 DESIGN / 512 CALIB / 512 REPORT; 20/33 candidate caps; 10,494,720 maximum candidate-world rollouts; zero states/labels | The design is now implementable and bounded, but it has not created training data or a stronger Teacher. External PASS may authorize capture-controller implementation only. |
| 08-09 | S4 point-banking exact-state screen | In rollouts, when the bot is already winning the trick and can retain a higher winner, let it bank a 5/10/K instead of always spending the cheapest winner. | **MECHANISM PASS / FULL-GAME SCREEN RUNNING** | overall acting-team point delta `+5.156`, one-sided LCB `+3.029`; attacker/defender means `+6.406/+3.906`; 35 wins, 4 losses, 25 ties; level utility `+0.25` | Banking a point-card winner while retaining higher control helps on the frozen exact-late trigger population in both roles. This is mechanism evidence; the fresh whole-game test is now running. |
| 08-09 | S4 complete-round score-free preflight v2 | Play complete mirrored rounds with the point-banking rollout rule, an analysis-identical null, and the live champion on the same deals and random streams. | **CAPACITY + PACKET PASS / SCREEN RUNNING** | 4 clusters in `321.32s`; projected screen `91.40` fleet-hours / `11.42` max-shard hours; treatment/null both trigger in both roles with exact dose | Exact `cad3992` repairs the superseded v1 validator, and Claude passed packet `17036e63…1385`. After S3a released Mini, one sealed 2,048-cluster screen consumed admission `1d99bb55…bdbf` and receipt `20a420d2…5cc`. |
| 08-09 | Human H0 counterfactual design v1 | Add the move a human actually played to the champion ballot alongside V11 and random proposals, then price those choices on common simulated worlds instead of imitating the human blindly. | **SPLIT REVIEW PASS / SUPERSEDED PRE-EXECUTION** | 384 DESIGN + 128 name-ID/deal-disjoint AUDIT plays; separate 36/9 buries; every eligible late/off-ballot row retained; zero outcomes | The split and authority semantics passed, but later executable audit found the pinned V11 digest names no artifact. V1 cannot parent a controller. |
| 08-09 | Human H0 counterfactual design v2 | Preserve v1's human sample while repairing the real V11 checkpoint and deployed report-LCB parent identities. | **IDENTITY DELTA PASS / SUPERSEDED PRE-CONTROLLER** | Claude PASS `9fdb67a`; same 384/128 plays and 36/9 buries; zero outcomes | The executable artifacts reopened correctly, but the analysis-ballot cap, downstream continuation and candidate-recall estimand remained ambiguous. Bounded v3 replaces the design before any controller or result. |
| 08-09 | Human H0 counterfactual design v3 | Cap the human/V11/random proposal union, make every source compete under fixed disjoint work, and distinguish the root report-LCB judge from the heuristic policy used inside rollouts. | **DESIGN PASS / CONTROLLER IMPLEMENTATION ONLY** | Claude PASS `239f13c`; 17/33 play/bury caps, three disjoint folds and 1,329,210 maximum candidate-world rollouts; zero outcomes | The human/model proposal experiment is now finite and executable. The PASS authorizes one score-free controller implementation—not a counterfactual run, label, training, strength claim or production change. |
| 08-09 | Human H0-v3 score-free controller v1 | Replay the frozen human decisions, build the production+human+V11+random candidate unions, and bind one future diagnostic run so incomplete work cannot look like a result. | **HOLD / SUPERSEDED BEFORE OUTCOMES** | 557/557 rows replayed; geometry `876ed56b…ff2b`; **0 worlds and 0 outcomes** | Packet `13d9a97f…61fc` is preserved, but Claude found the runtime did not self-enforce compiled/strict-void mode and receipt deletion could reissue admission. This is no verdict on human/V11 proposals; frozen controller v2 replaces it. |
| 08-09 | Human H0-v3 score-free controller v2 | Keep the same bounded human/model proposal experiment, but make the executable itself refuse weak sampler settings and consume an irreversible admission before it can publish a receipt. | **CONTROLLER PASS / ZERO OUTCOMES** | source `6977dbb`; packet `3f68dc6e…7fcf`; external marker `cc1c293`; 557/557 rows; strict runtime and deletion-proof admission independently reproduced | One T4 diagnostic execution is eligible. The PASS tested the machinery, not whether human or V11 proposals help; no label, training, strength or production authority exists. |
| 08-09 | S3a structured-bury full-game screen | Give the banker structured point/void/trump kitty options, then test the resulting policy over fresh complete mirrored rounds rather than selected bury states. | **SELECT NONE / CLOSED** | structured-minus-champion `+0.0464`, LCB `-0.0041`; structured-minus-null `+0.0430`, LCB `-0.0228`; all 2,048 clusters verified | The positive mean narrowly missed the preregistered gate, so no confirmation or deployment. Close the consumed stream without retry/tuning; only a separately preregistered fresh larger design could revisit the mechanism. |
| 08-09 | S3c exact-root curriculum + one-card controller | Start exact endgame work at naturally reached one-card endings, then advance to two and three cards only after each smaller problem proves bounded and useful. | **DESIGN + CONTROLLER PASS / ZERO SOLVER WORK** | 768 unique-deal roots; one-card actions all forced, two-card median/max 2/3, three-card median/max 3/7; packet `f58d23b7…3874` passed at `cc1c293` over 64 roots × 4 worlds | One bounded one-card mechanics/capacity run is eligible. This is not yet an action comparison or strength result; two-card work remains behind the next packet review. |
| 08-09 | S3a full-game score-free preflight | Check that structured-bury search is genuinely triggered, consumes exact work and fits Mini before the fresh full-game test. | **CAPACITY PASS / CONSUMED** | 4/4 clusters in 255.3 seconds; screen projection `72.62` fleet-hours / `9.08` max-shard hours | The sizing was correct and enabled the now-terminal screen. It was capacity evidence, not evidence that the policy would win. |
| 08-08 | S3b v2 throughput | Sample compatible hidden hands, solve the remaining four-card perfect-information game exactly by partnership minimax inside each sampled world, then average those exact world values. | **HOLD / NO SCREEN** | first exact-treatment cluster exceeded the frozen cumulative `250,000`-node cap; no receipt published | The registered four-card sampled-exact recipe is not operationally admissible under its zero-overflow rule. No strength conclusion; no retry or 2,048 screen. |
| 08-08 | S3a v2 sizing | Run a tiny score-free dry run to verify the structured-bury mechanism consumes exact work and fits available compute. | **CAPACITY PASS / NO STRENGTH VERDICT** | frozen projection `0.142` fleet-hours / `0.0178` max-shard hours, exact work and zero failed worlds | This cleared placement for the subsequently reviewed and completed 512-state screen; sizing itself made no strength claim. |
| 08-08 | S3a structured-bury screen | Compare strategy-aware point/void/trump kitty candidates with the live heuristic choice, the old four-choice search, and equally wide random candidates on fixed states. | **MECHANISM PASS / AUTHORIZE DUEL DESIGN** | structured-minus-live-incumbent `+0.997 +/- 0.401` (LCB `+0.597`); minus legacy-four `+0.878 +/- 0.380`; minus matched random widening `+3.253 +/- 0.561` | Structured proposal generation improved the frozen state-level bury objective against every preregistered control. This is the first positive S3 mechanism signal, but only a fresh full-game duel can establish bot strength. |

Evidence anchors, in the same order:

- RLCB-C1 aggregate `83f5a9df2f1db1fa45d50fb005b941b776d9ecc2c9f8703d3d62efff8f5ef5ea`.
- Formal S0 closeout `ef0a3659859b38d0b9362376e5e403fecb625f59c475600ed09906ce695fde9a`.
- DEV-512 state asset `af78748586034f6f97e96a167008b2c540c0e4b1670a683ef6b5f05ec85d3e7b`.
- V11 direct-v2 aggregate `b7c90ba4c1a9bb421a4cfcc788dbf1eb44365868f65ee0eb58257b38205d21ad`.
- Direct-Q aggregate `1fa6789eded784e03778f5ede841e45039579625477dbaa249d63c5ccc8ce791`.
- Suphx O0 gate `592a009aaf6fbd6680b6d9bab5e9738832050d1654b71dc6f2e19612d0bd407c`.
- Suphx O0-v2 gate `0dbd9aa8bdefb1980535e52cee7c8bcc0bb28f2759b9c20189db2c341bfff24e`;
  independent semantic replay returned `verified=true`.
- Teacher-v3 Stage-B gate `f607b48986aaa8b05194f88e8638540bc5c9360f09f3c28a7565d8d8cac89694`.
- Teacher-v3 fresh audit gate `8a1532b7b9a610452609bb2a7a69c9b13a9f1800ad74428d0278e9572aba91f8`;
  supervisor final `02f4f8b02d674ad3f59f9fa5b607692c7c8d31bdc5d26e2c64f66c983956f237`;
  terminal adapter `56ccefbd62d9ea2aef30a4c6e54e11a0d2231e464f129e754b84b3488f1c2442`.
- Teacher Stage-C-v3 packet `f213314ace8ead497fcaccde150d0694851069b970948a10d0823cf74ceb93b4`;
  source/asset `20bdb95` / `1a29418`; review remains open.
- S4 exact-state screen `abd9f36fa3e84c81b90e22f1c827f828a549f7fd6a9420ffbdb7c168974cdc00`;
  pre-outcome receipt `90124eb6f89c27cedc38770b2da5b3b8597400694281729656105f67803f526b`;
  admission `83993ec6609c2a7528853d4c1db789f137d3f0cbfff97d20fbf526cbd5ff5e6d`.
- S4 complete-round v2 preflight `fcc8b8913d80db5b1fe4bb7d6b727dc722bb7d0f4ec9c8806842535fc43ee060`;
  frozen packet `17036e6307ad0072ae10aeaaddde0ed3628a2f526ca440e909cdc35cd5071385`;
  running-screen admission `1d99bb55f780cb9f5a9f0ef99c810e0045eb99b458ff73d9190d8d59c60cbdbf`;
  receipt `20a420d2e939f8f1ce375ca32cee81d044db2c29dff7e52fbe7080a000dd65cc`.
- Human H0 v1 design packet `9ff160a9bc54a30daa85a07b29440f5c4cdd1c8feb4574f81c102158e46247d3`;
  repaired v2 packet `2cccf5803ca60cf41690f18dc0e85febaf36a88ce702587e8c86a67e2a358f2b`;
  bounded v3 packet `4d3f0a35082c6957f2a468686b8eedbd6d7cbbf9540503fcea08cccf27c8cc3c`;
  bounded-v3 design-review marker `239f13ce52a8be81108fdebf9bd0e96742e60133`;
  reviewed corpus manifest `b9699790bdfe1c217922c9f9c72b237c1856174fa64c11753329a8ff11e16553`.
- H0-v3 controller v1 packet `13d9a97f9adf26860b9f5e0d4889960c75baa5bf979b939206d2399472ba61fc`;
  replacement v2 packet `3f68dc6ec6d5f90043f36c0a68847ca9ef510641e01760ac4fa11ebd6a6a7fcf`;
  candidate geometry `876ed56bd8f436d58cb6f3d58774a0f06756afb4d8c98ffdb49d9424b545ff2b`;
  v2 controller/runtime `108e6bb2…379` / `ddf8b250…a124`; external PASS
  marker is recorded at `cc1c293`.
- S3a full-game aggregate `20609613e000ff4d11640dc35827527ca14e0ec09720c9c6cda1c64f6cdc271f`;
  terminal final `32156d79aaff247c2d3b60bcf45460442a224c31f415d6689b769b0eba32c9ff`.
- S3c census `236326099dc9763c6a5941bcb2a90670c4e23ac390ea07a0e4ec5063fa50b52a`;
  curriculum packet `df1024280a77c60174a57c3273ba3624e672bec9afde023576fde0404df49eca`;
  review marker commit `084ba7eba59cd0a317a50c4088f194d2376c1e03`;
  one-card controller packet `f58d23b74046dd04963b4f10fbf605030221219eef6d325c5e8319043643874a`;
  external controller PASS marker is recorded at `cc1c293`.
- S3a full-game preflight `09692f823d26d38ea76c7c6e36ea007a5031c0f05ca1a76795c84e7d0722edf0`;
  supervisor final `56943242f3620b09774a55eab992fbac0bce6ad224c3ada6a7b54a5634799e9f`;
  reviewed screen packet `de16247bfea13bde516cfb45317f7d21d46d758ae700441b9b747b41f3d5cdd4`;
  admission `567e8aa8bb1107314373f7e5756e4f8646e419a70fa1afed9594ee36edf41c5e`;
  live receipt `2c89bed3e5727b4e116f3efb2fcdc184cc1dc683860be66dd842a5310b6cbb2c`.
- S3b v2 closeout: clean head `cd44ea8a6fefb8fba258d01bcca4bed98169a217`,
  runner SHA `ed4252b2f957e2855446ca63858e7da973949934850684e8f92e5950ca74050d`;
  final and partial receipts absent by fail-closed design.
- S3a v2 sizing receipt `cf7702770e2dd416b0ecfcdcc2ba6a5c32ab262aef0319d87346d05bcdf5c431`.
- S3a screen aggregate `74aa5a3947e1daaa5aa4bc33eef8ae04eaaf695d0cb900c7045eb0cbbc4396cd`;
  supervisor final `d3f2b1ab48085ccf37534b5dd7f20ea6cf0d7644c6c49304b644ecf895169a6b`.

### Production search

- **Live policy:** compiled `mc-s0-report-lcb`, Fly release 17, image
  `latency-cd6789e`, digest `047bcfe4...5b300`; `mc-strong` is the
  policy rollback. N=30 nominates a challenger, a disjoint R=300 common-world
  fold rechecks the fixed pair, and only a positive one-sided paired LCB
  overrides the incumbent.
- **Evidence boundary:** S0a/S0b and fresh RLCB-C1 were independently positive;
  the canonical table carries the confirmation. Equal work did not explain the
  gain, adaptive allocation added no resolved increment, and N=60 did not beat
  N=30. Formal S0 remains a separate unread/nonretryable SELECT NONE.
- **Runtime boundary:** release 17 preserves decision semantics while moving an
  isolated snapshot off the event loop, overlapping pacing and discarding stale
  work before commit. Live claim/reconnect/X-ray and ordinary-room timing passed;
  concurrent multi-room tails remain open. See `PERF.md` and `DEPLOY.md`.

### Correctness, sampler and data

- Package H passed bounded hard validity/support on original, late and deep
  reservoirs under compiled strict execution. It does **not** prove posterior
  calibration or a globally complete constructive dealer. Physical-deal bias
  remains material; posterior-changing sampler flags stay off.
- DEV-512 selected none: the shipped ballot had the lowest equal-work regret and
  CALIB/REPORT remain sealed. This rejects its registered designs, not every
  future proposal-search hypothesis.
- S3a supplied a real state-level proposal-search signal for bury decisions,
  but the fresh 2,048-cluster full-game screen terminally selected none. The
  broader ballot remains useful diagnostic evidence; this exact policy recipe
  is closed without confirmation, retry or tuning on the screen.
- High-N and late assets are replayable state reservoirs, not oracles; their
  labels use old ballots, non-strict sampling, raw points and heuristic
  continuation. Relabel fresh named strata under the current contract.
- The August 9 Fly-snapshot-only human refresh replayed 122 complete rounds and
  accepted 2,830 plays plus 45 buries under the repaired public/no-private-
  kitty encoder. It explicitly rejected seven incomplete rounds, excluded 12
  legacy local-only rooms, found 25 human plays outside the broad exhaustive-
  follow analysis ballot, and found points in 22/45 human buries. This is
  proposal/coverage evidence, not proof that human actions or round-return
  labels are stronger. Use player/deal-disjoint splits and counterfactual
  relabeling before training beyond a separately measured BC control. Its
  current split is disjoint by pseudonymous player name and deal, but cannot
  prove true-person disjointness when one person changes names; H0 is therefore
  a diagnostic proposal pilot, not people-strength evidence. Clean
  producer is `b52dc33`; corpus manifest SHA-256 is `b9699790…16553`.
- Encoder identity includes semantics and transitive bytes. Drifted banker-
  private-kitty assets remain quarantined; `gen_v4_all`, which trained
  v11pair, is clean. House progression is uncapped; `+/-3` is only a named
  legacy RL target.

### Human-observed policy surfaces

- **Kitty:** production is strongly point-shy rather than incapable of
  burying points. S3a's point/void/trump alternatives improved the selected
  512-state objective, but the fresh whole-game screen selected none. Do not
  ship or retune this recipe; use its disagreement states as future Teacher or
  proposal diagnostics.
- **Point banking:** root MC can source a point-bearing winner, but shared
  heuristic continuation selects the cheapest winner when a cheaper non-point
  winner also exists. S4 v1 is closed HOLD without outcomes because its
  material digest was irreproducible. Exact `1b35fb7` now supplies the fresh
  reviewable replacement outside sealed MCBot/registry bytes: treatment and
  matched null share analysis, preserve the root ballot and baseline contest
  choice, act only last, and require a higher winning reserve. Named
  continuations demonstrate both +10 immediate value and -10 future-control
  risk. Independent score-free verifier
  `b0ef0f9` rescanned all 69,047 ascending deals and rebuilt every stored row
  exactly at witness `3079fb16…f0a9`. Claude passed review, and the only
  one-shot Air screen then verified terminal result `abd9f36f…cdc00`: overall
  point delta `+5.156` (LCB `+3.029`), positive means in both roles, 35/4/25
  wins/losses/ties and level utility `+0.25`. This establishes the narrow
  exact-late mechanism. The first full-game packet was superseded before
  review or launch after adversarial probes exposed outcome-sign, bound, work
  and authority gaps. Exact `cad3992` implements the repaired natural-traffic
  treatment/null/champion comparison; score-free preflight `fcc8b891…ee060`
  passed and packet `17036e63…1385` independently closed PASS at Claude marker
  commit `51a864c`. After S3a closed, the one admitted 2,048-cluster Mini
  screen launched under admission `1d99bb55…bdbf` and receipt
  `20a420d2…5cc`. Its outcome remains sealed; it is not yet bot strength,
  confirmation or production authority.
- **People-facing target:** human agreement is a style/coverage diagnostic.
  After bot-vs-bot confirmation, a blinded opt-in `HUMAN-C1` must compare the
  candidate with the live champion across the same human cohort, balanced by
  team/banker/seat and clustered by player session. Evaluation games never
  enter training or selection. Forward-only guard through `b198839` makes the
  human-corpus builder refuse the whole publication if any round carries the
  HUMAN-C1 schema or a `training_excluded=true` tag. Physical separation is
  now backed by inert room primitives through `340ae4e`: a disjoint root,
  hidden complementary blocks, derived participant-pair identity, per-arm
  policy/Git/image/ballot identity, exact 0/2-human versus 1/3-bot enforcement,
  name/chat redaction and fail-closed evaluation writes. No WebSocket path can
  construct such a room. Exact `6082589` also makes a bound-human disconnect
  during an assigned in-progress game terminal: it records only a redacted reason and
  stops bot cover, takeover, declaration, dealing and round advancement.
  Completed games remain valid, stale socket teardown is a no-op, and ordinary
  rooms retain their old behavior. The focused corpus/server battery passes
  82/82 locally and independently on Air. Exact `859a26e` adds an inert
  assignment constructor: a score-free reviewed design binds both arm
  policy/Git/image/ballot identities; two consent facts must
  match cohort and consent version; and the secret-derived arm and opaque
  session ID are complementary, deterministic and design-domain-separated.
  Clients still cannot reach this path or choose an arm/session. Its expanded
  focused battery passes 88/88 locally and on exact Air. Durable one-use
  issuance and authenticated consent ingress remain closed. Exact `fff688b`
  adds fail-closed runtime reopening: the assigned arm must match the runtime
  Git and image, its named policy is reconstructed from the registry, and all
  executable ballot stages are independently rederived and compared with the
  reviewed identity. No caller may inject a lookalike bot. The expanded suite
  passes 94/94 locally and on exact Air. Exact `f387a30` then adds the immutable
  receipt source: it requires hash-pinned stable bytes from a regular unlinked
  file, exact design/active-policy identity, and explicit identity-only / no-
  human-traffic authority before reopening. Symlinks, hard links, digest,
  schema, authority, design and policy drift all fail closed; 100/100 focused
  tests pass locally and on exact Air. Exact `064988f` adds durable one-use
  slot reservation keyed independently of the secret-derived session ID;
  exclusive publication permits one concurrent issuer, fsyncs file/directory,
  and leaves interrupted writes consumed rather than retryable. The reservation
  itself is identity-only and grants no traffic, training or promotion. The
  104-test battery passes locally and on exact Air. A real candidate-specific
  receipt freeze/review, authenticated consent ingress, synthetic C0 and the
  terminal analyzer remain launch blockers.
  The earlier
  repair scans tags
  before malformed-round rejection and terminally invalidates an evaluation
  room after any log-write failure, so neither path can manufacture a partial
  training or evaluation publication.
- **Human proposal pilot:** exact `9770313` froze score-free H0 v1 at packet
  `9ff160a9…247d3`: 384 DESIGN and 128 player/deal-disjoint AUDIT play keys plus
  separate bury surfaces. Its split review passed, but executable audit found
  V11 SHA `0260ad67…455e` names no artifact. Exact `12dac55` v2 preserved the
  rows and repaired executable `ep07.npz` plus the portable live parent; Claude
  passed that delta at `9fdb67a`. A later score-free implementation audit found
  its action cap, downstream continuation and candidate-recall output
  underdefined. Exact source `b02b6de` / packet commit `d6214ce` freezes
  bounded v3 at `4d3f0a35…8cc3c`: 17/33 play/bury caps, explicit
  `HeuristicBot` continuation, three disjoint folds and maximum 1,329,210
  candidate-world rollouts. Claude independently passed the design at
  `239f13c`. Exact producer `931f504` and asset `ff277b4` froze controller v1
  packet `13d9a97f…61fc`: all 557 rows replayed, geometry is
  `876ed56b…ff2b`, and preflight consumed zero worlds/outcomes. Claude held v1
  because runtime mode was not self-enforced and receipt deletion could reissue
  admission. V1 remains immutable. Replacement source `6977dbb`, asset
  `d99f7e8` and packet `3f68dc6e…7fcf` now require compiled/strict-void runtime
  on every packet open, reject experimental sampler flags and publish a durable
  admission slot before the receipt. Score-free freeze/recompute still consumed
  zero worlds/outcomes. Claude independently passed v2 at `cc1c293`, making one
  later H0 diagnostic receipt eligible; the marker grants no labels, training
  or strength authority.
- **Teacher Stage C:** v1/v2 are superseded design artifacts. Frozen v3 source
  `20bdb95`, asset `1a29418` and packet `f213314a…3b4` bind the passed H0
  controller, exact live parent and canonical adapter to a finite 2,048-state
  design (1,024 DESIGN / 512 CALIB / 512 REPORT; 1,920 play + 128 bury).
  Ordinary anchors use 256+256 disjoint worlds; hard-tail candidates use 64
  selection worlds and a fixed-winner 300-world report, with optional 128+600
  audit, 20/33 caps and a 10,494,720-work ceiling. `HeuristicBot` continuation
  makes recursive MC work exactly zero. External design review is open and
  grants no capture, label or model work before PASS.

### Learned policies and RL

- V11pair's confirmed 57.7% result over SmartBot shows within-ballot ranking
  signal, but direct-v2 selected none against current search and rejected
  protected composition. Use it only as a bounded proposal/ranking and teacher
  diagnostic, never a scalar leaf.
- v13 fit its offline target better without improving play; existing value-leaf
  and learned-rollout hybrids have no verified gain. A private observation has
  no strategy-independent scalar value without a named belief/continuation.
- Direct-Q's positive gameplay tail failed held-out role learning. Suphx O0's
  aggregate oracle-public signal failed seed robustness and stayed nearly
  uniform. O0-v2 then completed the fresh eight-seed shared-public CRN
  mechanism battery: coupling and semantic replay passed, but the control
  cell's oracle-minus-public LCB was `-0.067` and margin sharpening moved the
  mean down by `0.062`. All select none. The next learner needs a new target,
  credit/data or adaptation mechanism—not O1 or another estimator-only repair.
- Historical DMC2 had role-target, actor and promotion defects and was not a
  faithful AWAC/Suphx/DouZero implementation. Preserve its alarms, not its
  algorithmic verdict.

### Execution ownership

This ledger intentionally carries no live queue. Current order, blockers,
machine assignment and milestone gates live only in `BACKLOG.md`. The durable
conclusion is that new S3 mechanisms must bind exact report-LCB, Teacher scale
waits on its champion/hard-tail gates, V11 is proposal/diagnostic only, and a
fresh learner must change the target, data/credit assignment or adaptation
mechanism under the now-proven CRN/replay evaluation boundary.

## Using policies

Registered by name in `server/shengji/ai/registry.py`; the source fallback is
`mc`, while production explicitly sets `SHENGJI_BOT=mc-s0-report-lcb`:

```bash
SHENGJI_BOT=smart uv run shengji-server   # e.g. an easier table
```

Benchmarking uses factories, deterministic policy seeds, and mirrored deal
clusters. The factory seed boundary is now tested and constructor failures are
not swallowed. `play_pairing` and Elo pools remain selection tools; every
strength claim goes through `scripts/evaluate.py`, which writes exclusive
per-seed/per-flip records and a manifest, clusters uncertainty by deal seed,
enforces the preregistered bar, and reports the paired arm-minus-control
contrast.

```python
from shengji.ai.registry import make_bot
from shengji.ai.tournament import play_pairing

make_a = lambda **kw: make_bot("mc", **kw)
make_b = lambda **kw: make_bot("smart", **kw)
play_pairing(make_a, make_b, n_seeds=150, seed0=1_000_000)
```

Multi-policy Elo: `uv run python -m shengji.ai.tournament`. Human-agreement
tripwire: `uv run python scripts/eval_vs_human.py "../logs/*.jsonl"`. Pool Elo,
unpaired blocks, and small-n rates are selection screens, not strength claims.

## Active policies

### `mc` — base MCBot (source fallback, not production)
Determinized Monte Carlo (`ai/mcbot.py`): samples 10 opponent-hand worlds
from public card counts and hand sizes, then rolls a bounded ballot to round end
with heuristic continuations. The count-first allocator consumes declaration
pins, suit voids, and remaining-pair constraints; normal mode may still use its
final void-relaxing retry, while confirming runs require strict voids. The
independent full-history certifier remains open, and even a legal-world sampler
is not automatically a calibrated posterior. It is determinized search, not a
certified belief model. Choice is guarded by:
- **Confidence margin** (5.0 pts/round): candidates[0] is SmartBot's pick;
  the search overrides only when it wins by the margin. Rollouts are
  noisiest early; the margin is worth ~45 Elo vs pure argmax.
- **TRACTOR_LOCK**: heuristic tractor leads are final (56% vs unlocked).
- **Point-shy tiebreak** (2.0): among near-tied candidates, risk the fewest
  points (a beaten 10-10 lead gifts 20 immediately).
- The compiled path materially reduces full-round simulation cost but does not
  repair belief correctness. The base N=10 policy is retained for controls;
  `mc-strong` N=30 is its verified stronger search-dose descendant.
- Most other hyperparameters were flat: margin 5 was best in its grid,
  candidates 8 was enough, SmartBot rollouts tied at about 5x cost, and
  `LEAD_MARGIN`, `LEVEL_OBJECTIVE` and the old four-choice `MC_BURY` did not
  establish gains.
- vs SmartBot v2: 36-4 (90%) mirrored full games, n=40.
- Exposes `last_eval` (per-candidate values) for search distillation, and
  powers the /debug/xray live inspector.

### `mc-s0-report-lcb` — production

Runs the complete `mc-strong` N=30 ballot and selection, nominates one
challenger, then compares that fixed pair on 300 disjoint common worlds. It
overrides candidate 0 only when a conservative one-sided paired Student-t LCB
is above zero; short folds fail back to candidate 0 and all accepted work is
recorded. S0a measured `+0.353 +/- 0.069` and S0b independently measured
`+0.357 +/- 0.066` versus `mc-strong`. A compiled preflight on the named hard
lead state measured 0.390s median versus 0.127s for `mc-strong`. It was manually
deployed for strength on 2026-08-07, with `mc-strong` as rollback. Formal fresh
RLCB-C1 confirmation is complete: on 2,048 new paired clusters the exact
production rule measured `+0.338379 +/- 0.067706` versus `mc-strong`, while the
collision-free current-policy null was `-0.019043 +/- 0.068270`. This confirms
one-round paired level-utility superiority only; it does not prove multi-round
progression or authorize changes to N, R, ballot, sampler or confidence rule.

### S4 point-banking arms — experiment-only, not globally registered

`make_point_banking_bot()` in `ai/point_banking.py` constructs the exact
`mc-s0-report-lcb` class with either the treatment or trigger-matched-null
rollout policy. Keeping these names out of the shared registry preserves the
source identities bound by terminal RLCB/Teacher evidence. Both arms retain
the champion's root ballot, selection/report work and RNG stream; only rollout
continuation differs. They have no production, training or strength authority.

### `smart` — SmartBot v3
`ai/smart.py` + `ai/memory.py`: heuristic layered with public-information
memory — card counting, boss detection ("is this the highest card still
out?"), void inference, ruff/beat risk. Leads safe throws (every component
provably unbeatable) → boss pairs/tractors → tractor pressure → boss
singles; always contests in-suit (tempo); spends trump only on tricks worth
taking; feeds points only when partner's win is secure; buries toward voids
gated on trump strength; endgame control (contest everything in the last ~6
tricks); eager declaration (8/6 thresholds).
Lineage (all mirrored vs heuristic): v1 (memory only) 66% → v2 (+safe
throws +17pt, bury-to-void, eager declare) 86% → v3 (+endgame control +2,
trump-gated bury +1) ~88-90%. Registry keeps smart-v1/smart-v2 reproducible.

### `heuristic` — baseline
`ai/heuristic.py`: stateless rules; the fixed reference (Elo anchor 1000).

### `rl` — RLBot (experimental, opt-in)
`rl/torch_policy.py`: net argmaxing over enumerated legal actions; needs
`uv sync --group rl` + `SHENGJI_RL_CKPT` (checkpoints local, gitignored).

The standalone checkpoint line is paused as a strength target and retained as
a cheap diagnostic/deployment baseline. The durable learned-policy conclusions
are:

- `v11pair` is useful as an exact-ballot root proposal/ranker; it beat SmartBot
  but has no valid superiority result over MC and cannot be used as a generic
  scalar leaf.
- v13 fit its offline target better without improving play. Offline loss and
  old-surrogate agreement are not promotion metrics.
- Ballot or encoder changes invalidate trained checkpoints even when tensor
  dimensions stay constant. Every consumer must bind semantic identity and
  rerun its direct gate.
- Replacing the rollout policy and the tested value-leaf hybrids did not
  establish gains. Preserve the complete root ballot; corrected direct-v2
  rejected v11 protected anchoring, so learned signals remain bounded
  proposal/ranking or teacher diagnostics until a new contract passes.
- Historical DMC/DMC2 runs exposed action-spread collapse, a role-sign defect
  and incomplete algorithm fidelity; they do not reject AWAC, Suphx or
  DouZero. The repaired Direct-Q screen produced positive gameplay but failed
  its held-out learning gate and selected none; the next learner must use a
  separately frozen recipe rather than extend 144M.

The authoritative model-by-model chronology, including v1-v13, lives in
`RL_PLAN.md`; exact old run narratives live in `server/runs/` and the dated
archive.

## Cross-policy correctness and identity

- **Engine semantics:** tied effective codes preserve physical card identity;
  throws can be ruffed; failed throws force the lowest beatable component;
  pairs are beaten only by higher pairs; level progression is uncapped under
  the house rules. Historical evidence measured before these corrections is
  not directly comparable to current play.
- **Sampler knowledge:** declaration pins, known banker kitty, suit voids,
  remaining pairs and remaining tractor runs are consumed once. Package H
  passed the bounded strict validity/support gate on original, late and deep
  reservoirs. Posterior calibration and global constructive completeness are
  still open.
- **Public memory:** forced follow responses update suit void and pair/run caps;
  search may use only information derivable from public history plus the
  acting player's private hand.
- **Reproducibility:** factory seeds reach every stochastic policy; deck and
  ballot iteration are ordered; caches use canonical keys and return defensive
  copies; strict evaluation refuses short or zero-world searches and records
  sampler counter deltas.
- **Artifact identity:** policy evidence binds source, ballot, sampler,
  continuation, encoder semantics and transitive bytes. The drifted
  banker-private-kitty assets remain quarantined even though their vector
  dimensions match clean assets.

## Toggle registry (canonical) — every flag, what it does, and its record

**SmartBot / HeuristicBot** (h2h = head-to-head vs same bot without the flag):

| flag | default | what it does | record | verdict |
|---|---|---|---|---|
| SAFE_THROWS | ON | leads multi-part throws (甩牌) only when card-counting proves every part unbeatable — free multi-card winners, penalty can never trigger | +17pt vs heuristic | adopted |
| CONTROL_LEADS | ON | when in the lead with no boss cards: try pairs (J+) first, then empty a 1-2 card suit, then a forcing high non-point single — junk only as true last resort | 67% h2h, n=150 | adopted |
| LATE_TRUMP_PAIRS | ON | with ≤12 cards left, lead the top trump pair — depleted opponents can't answer pairs (mined from human play: +7.3/decision, 8/8) | 60% h2h, n=150 | adopted |
| VOID_DUMP | ON | when discarding junk, shed from the SHORTEST suit first — empties suits to open future ruff opportunities | 55% h2h, n=150 | adopted |
| TEMPO_GUARD | ON | refuses to spend rank-trumps/jokers winning tricks worth 0 points (prod bot once burned BJ beating a rank-4 for nothing) | root-fix, verified on position | adopted |
| ENDGAME_CONTROL | ON | in the last ~6 tricks, contest every winnable trick regardless of points — controlling the finish beats saving cards | +2pt | adopted |
| BURY_TRUMP_GATE | ON | banker buries kitty points only when trump is strong enough to defend the last trick (11+ trumps incl. big joker); weak trump = never bury points | +1pt | adopted |
| BURY_VOID | ON | banker's bury deliberately empties 1-3 card suits (ruff setup) instead of spreading discards | ~+1pt | adopted |
| DECLARE 8/6 | ON | declares trump at 8 projected trumps (7 in the grace window) — eager beats waiting for a perfect hand (10/8 measured −4) | +2pt vs 9/7 | adopted |
| SAFE_TRACTOR_ONLY | ON | won't lead tractors into suits where an opponent has shown void (they'd get ruffed) | disabling: −4 | adopted |
| TEMPO_SEEK v2 | off | spends trump (even jokers, if the prize is big) to win the lead when boss pairs/tractors are waiting to be played | v1 48%, v2 53%, combo 49% n=200 | tie — noise |
| ANY_PAIR_OVER_JUNK | off | last-resort leads prefer any pair (even low) to a passive low single | 52%; combo 49% | tie — noise |
| TRACTOR_FIRST | off | ranks tractors above boss pairs in the lead order | 51% h2h | tie (tractors already led at step 2) |
| PARTNER_VOID_LEAD | off | leads suits your partner is void in so they can ruff for points | 50% alone, −4 combined | rejected |
| DECLARE_TUNE | off | declares the WEAKER of two long suits + extra-eager on point levels (5/10/K) — folk wisdom from strategy guides | −2pt | rejected |
| TRUMP_DRAIN | off | leads boss trumps from long holdings to strip opponents' trumps early | −4pt | rejected |
| TRUMP_DRAIN_V2 | off | same idea, banker-side only with cheap trumps (expert-conditioned version) | −4pt | rejected |
| FEED_ON_TRUMP | off | throws point cards to a partner winning with trump even when they could be overtrumped | −9pt | rejected |
| RESERVE_LAST | off | attackers hold back a boss pair/tractor for the last trick (kitty multiplier) | −11pt | rejected (hoarding loses) |
| POINTS_DRY | off | once points-in-circulation hits 0, stop spending premium trumps outside the endgame window (user idea; Memory.points_left is exact from public info) | 100-100, 50% n=200 | tie — the regime is real but rare + TEMPO_GUARD/search already cover most of it; points_left() kept in Memory for future consumers |
| ACE_SEQ | off | cash boss singles in follow-able suits before ruff-risky ones (expert research #1) | 50% h2h n=200 | tie — search/ruff-risk already covers it |
| NO_OPEN_POINT_SUIT | off | don't open point-bearing suits without their boss (expert research #3) | 50%; combo also 50% | tie |
| TEMPO_SEEK v2 (re-test 08-03) | off | re-measured on the current stack + fast engine | 98-102, 49% n=200 | tie confirmed |
| DECLARER_PIN | **ON** | sampled worlds place the declarer's SHOWN cards in the declarer's hand (public info the sampler ignored) | **60-60, 50% n=120** | KEPT on correctness grounds: provably-correct information, fixes verified blunders (RTLT R9 T1 flips), costs nothing. Correctness-grade changes must not LOSE, not necessarily win. |
| KITTY_POINT_POLICY | off | expert research #2: numeric bury caps — locked hand (13+ trumps, BJ) deliberately banks 10s/Ks behind the kitty multiplier; weak trump makes points near-unburiable | 101-99, 50% n=200 | tie |
| TREE_PLANTING (树套) | off | expert research #4: with a 6+ card side suit holding top pairs, lead LOW early to exhaust the suit, then run the retained tops (deliberately overrides pairs-first) | **90-110, 45% n=200**; combined with kitty 46% | **rejected — the only expert candidate to measurably HURT** |
| BANKER_KITTY | **ON** (correctness) | the banker counts its OWN buried cards as known | **149-151 = 49.7%, Wilson95 [44.0%, 55.3%]** (n=300, fixed code, seeds 900k, `scripts/kitty_duel.py`) — no measurable strength effect either way | kept because it is true information the sampler already used; the three earlier duels are VOID (they ran while this flag silently disabled banker search — incident 2026-08-03) |
| SIZE_FIRST | off | strict "more cards is better" lead order: any ruff-safe tractor, then any ruff-safe pair, before all smaller leads | 52% h2h, n=200 | tie (consistent with its halves TRACTOR_FIRST + ANY_PAIR_OVER_JUNK both null) |
| PAIR_VOID_BOSS | off | leads a LOW pair once every opponent has PROVEN pair-void in its suit (forced pair-matching makes a broken answer proof) | 54% first n=200, 48% fresh n=200 → 51.0% at n=400 | tie — small-n mirage caught by extension; `Memory.pair_void` remains a correctness input |

**MCBot** (search-level knobs on top of SmartBot):

| knob | value | what it does | record | verdict |
|---|---|---|---|---|
| MARGIN | 5.0 | SmartBot's pick is the incumbent; the search only overrides it when a candidate wins the rollouts by 5+ points/round — guards against early-round rollout noise | beat argmax 62% (~45 Elo) | adopted |
| N_DETERMINIZATIONS | base 10; strong/prod selection 30 | hidden-hand worlds per candidate | fresh current-main N=30 minus N=10 `+0.222 +/- 0.140`; N=60 minus N=30 `-0.002 +/- 0.119` | N=30 adopted; no width-only case above 30 |
| MAX_CANDIDATES | 8 | how many candidate plays the search evaluates | 4→58%, 12→60% | adopted |
| TRACTOR_LOCK | ON | when the heuristic wants to lead a tractor, that's final — no rollout override | 56% h2h | adopted |
| POINT_SHY_EPS | 2.0 | among near-tied candidates, play the one risking the fewest points (a beaten 10-10 lead gifts 20) | from the 10-10 lead analysis | adopted |
| LEVEL_OBJECTIVE | off | scores rollouts by scoring brackets (the 80/40-point cliffs) instead of raw points | 59% vs 62% ref | tie |
| MC_BURY | off | searches the banker's bury: heuristic pick vs loose/strict/no-void variants over sampled worlds | 62% = ref | tie |
| LEAD_MARGIN | off | a higher override bar for leads specifically | 8/12/999 → 51/47/50% | tie |
| SmartBot rollouts | off | uses the memory-aware bot instead of the fast heuristic to play out sampled worlds | tie at 5x cost; **RE-TESTED 2026-08-03 with SmartBot now 93 Elo above heuristic: 62-58 = 52%, still a tie** | rejected — twice, on cost. Both are FAILED SUPERIORITY tests: a 93-Elo-stronger roller did not win, which does NOT establish that rollout strength is irrelevant. The honest reading is that no continuation has been shown stronger at 5x cost; equivalence was never tested. |
| RISKY_THROWS | off | puts near-boss throws (A+QQ where only one higher pair threatens) on the ballot; worlds price the risk | 53% at MC, n=120 | tie; combined arm unmeasured and not prioritized |
| TRUMP_BALLOT | off | adds trump-pair and top-trump lead candidates (钓主) for the worlds to price | 53% at MC, n=120 | tie; combined arm unmeasured and not prioritized |
| WIDE_LEAD_BALLOT | **ON** | leads roll out EVERY pair, tractor, and near-boss throw in every suit incl. trump (lead cap 8→14). Fix for the JVRA sourcing gap: ♣A♣A/♣8♣8 never reached the rollouts | **62% vs narrow mc (75-45, n=120), +7% latency** | **adopted — largest MC gain since the margin rule; sourcing > preference confirmed** |

**Engine corrections** (not flags — permanent): throw-ruffing (all bots
can contest 甩牌), pair_is_boss (+13pt), beats() alternative
decompositions, defend-at-A, format-scaled kitty multiplier, throw
penalty forces the beaten component, exhaustive-follow enumeration
(analysis-side).

## Durable decision rules

- **Name the reference.** “Current” and “champion” are not identities.
  Strength work freezes the exact live policy and a matched null; today that is
  `mc-s0-report-lcb`, not formal S0's `mc-strong`.
- **Guarded paired reevaluation is the proven search mechanism.** Ordinary
  N=30 nominates; a disjoint R=300 common-world report fold overrides only on a
  positive conservative LCB. More uniform width and adaptive allocation have
  not shown an additional gain.
- **Screens reject/select designs; confirmations establish strength.** Elo,
  human agreement, offline regret and small blocks may prioritize work, but
  promotion requires deterministic factories, paired deal clusters, an
  explicit null, exact work/counters, immutable manifests and fresh evidence.
- **Correct data is a named estimand.** Ballot, sampler, continuation, role,
  perspective, utility, encoder semantics and transitive bytes are part of a
  target. High-N/late assets are replayable reservoirs, not generic oracles;
  drifted banker-private-kitty encodings remain quarantined.
- **A legal sampler is not automatically calibrated.** Package H proves bounded
  strict validity/support on its registered reservoirs. Posterior fidelity and
  global constructive completeness remain separate questions.
- **Learned models need an identifiable role.** Pairwise V11 scores may
  propose/rank within a ballot but are not scalar leaves. Better offline fit
  did not imply better play. Direct-Q and O0 failures require a fresh,
  mechanism-isolating learner experiment, not more compute on inspected runs.
- **Correctness and throughput are gates, not strength.** A fixed engine bug,
  green code gate, faster simulator or larger corpus enables an experiment; it
  does not count as an AI win.
- **House progression is uncapped.** A clipped `+/-3` value is legal only as
  an explicitly versioned legacy RL target, never as an engine/evaluator
  validator.

## Archive boundary

The former dated working notes are recoverable at
`git show ca556c2:AI_POLICIES.md`. Day-by-day evidence lives in
`docs_archive/daily-log-2026-08-04.md` through the current daily log.
`RL_PLAN.md` owns model lineage and design rationale; this file keeps only
callable policy/toggle contracts, canonical terminal results and conclusions
that still govern decisions.

## Reproduction pointers

| topic | durable source |
|---|---|
| callable policies and flags | this file + `server/shengji/ai/registry.py` |
| model v1-v13 chronology | `RL_PLAN.md` |
| current execution order | `BACKLOG.md` |
| exact run/artifact status | `JOBS.md` |
| sampler/engine boundary | `CORRECTNESS.md` |
| reviewer decisions and retractions | `HANDOFF_REVIEW.md` |
| full removed working notes | `git show ca556c2:AI_POLICIES.md` |
