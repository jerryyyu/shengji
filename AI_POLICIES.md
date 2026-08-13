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

## Current synthesis — 2026-08-12 23:25 EDT

### At a glance

- **Live champion:** the two-stage Monte Carlo policy is still the only
  confirmed and deployed strength gain.
- **Closest learned challenger:** the model now helps when it proposes one move
  after trick five and fresh Monte Carlo search remains the judge. That passed
  a fresh state test; its first whole-round screen is running with no verdict.
- **Closest rollout challenger:** point-aware rollouts were positive twice. A
  fresh prospectively accumulated confirmation is now running on Cloud; old
  outcomes never enter its estimator.
- **Other live strength tests:** the mid/late learned-search hybrid runs on
  Mini and pair-aware continuation runs on Air. S6 is reviewed and queued
  behind Air; none has a readable terminal outcome yet.
- **Main model lesson:** more data produced stable outcome prediction, but a
  model choosing moves globally did not transfer. Specialization plus search
  protection is the first learned use to pass fresh evidence.

### Canonical outcome summary

Rows are grouped by scientific conclusion, not by controller version. A
**lower bound** is the conservative edge after uncertainty; a positive lower
bound clears the registered screen. Exact operational history and hashes stay
in the collapsed evidence section and dated logs. The **short label** is the
canonical abbreviation to use in discussion, issue titles and run names; it
does not replace the plain-English strategy.

| short label | area | strategy in plain English | status now | best result | learning / what is next |
|---|---|---|---|---|---|
| **RLCB** | **Production champion** | Let 30-world Monte Carlo nominate a move, then compare it with the heuristic choice on 300 fresh shared hidden worlds and override only with conservative evidence. | **Deployed and confirmed** | `+0.338 +/- 0.068` signed levels versus the previous 30-world policy; matched extra-work control was flat. | The two-stage search rule is genuinely stronger. It is the named baseline every challenger must beat. |
| **S0-ALT** | **Other confidence and allocation rules** | Try wider search, adaptive allocation, and alternative confidence rules. | **Closed; no additional winner** | The formal suite failed before readable outcomes; separate wider/adaptive tests found no resolved gain. | Do not reinterpret the unread run. New work must change proposals, continuations, or model use rather than only reshuffle the same search budget. |
| **T3-DATA** | **Teacher data and training** | Counterfactually label hard decisions, grow from 1,536 to 7,040 training states, and train complete eight-seed model cohorts. | **Reusable model/data capability; not a strength win** | The larger cohort was stable across seeds; outcome prediction improved strongly (`+0.47845`, lower bound `+0.44201`). | The pipeline and 7,040-state asset are useful. More identical rows are not enough; future data must contain meaningful alternative actions, source tags, and better continuation policies. |
| **T4-GLOBAL** | **Model chooses moves globally** | Let the learned ranker choose or override moves across all phases. | **Closed for this model generation** | Protected fresh test: `-0.00823`, lower bound `-0.01894`. Powered uncertain-state test: `+0.01213`, lower bound `-0.00506`. | The model predicts outcomes better than it ranks actions. Do not deploy global model argmax or tune the spent tests. |
| **T4-MIDLATE** | **Model proposes inside search after trick five** | Let the model offer one move only in middle/late play; fresh 300-world Monte Carlo search still decides whether to replace production's move. | **Fresh state screen passed; whole-game screen running** | Versus live: `+0.02020`, lower bound `+0.01275`. Versus an equally expensive uninformed proposal: `+0.01570`, lower bound `+0.00880`, on 256 fresh states. | First evidence that the learned model adds value inside search. The sole fresh whole-round screen is running on Mini; it must beat both live and same-work uninformed widening before a confirmation may be designed. |
| **S4** | **Point-aware rollout policy** | In simulations, bank a point card when already winning a trick instead of mechanically spending the cheapest winner. | **Promising; fresh sequential confirmation running** | Whole-round estimates were `+0.08691` (lower bound `+0.03075`) and independently `+0.04883` (lower bound `-0.00688`). | Direction was positive twice. A disjoint, prospectively reviewed 8,192/16,384-cluster test now runs on Cloud to resolve a useful `+0.04` effect; old outcomes never enter its estimator. |
| **S3A / T4-BURY** | **Kitty and bury choices** | Offer structured point/void/trump buries or use the learned bury ranker. | **Current versions closed; narrow signal remains** | Structured whole rounds: `+0.0464`, lower bound `-0.0041`. Learned bury on 32 fresh choices: `+0.0338`, lower bound `-0.0153`. | Both estimates were positive but inconclusive. Preserve the point-and-void clue for a candidate-rich, properly powered successor rather than retrying either spent recipe. |
| **V11** | **V11 pairwise model** | Learn which ballot move beats the heuristic choice, then use that model directly or behind a protected fallback. | **Direct use closed** | Confirmed 57.7% versus SmartBot, but `-0.141 +/- 0.070` versus the live champion. | The model has proposal signal but does not beat current search. Retain it only as a proposal and disagreement source. |
| **DIRECT-Q** | **Direct return learning** | Learn action values directly from complete-game returns instead of imitating Monte Carlo. | **Closed at learner gate** | Gameplay tail was `+0.163 +/- 0.059`, but held-out learning failed for one seed and both pooled roles. | Interesting clue, not a promotable model. A successor must change credit assignment or specialize surfaces and pass across seeds. |
| **O0** | **Training with all cards visible** | Train an oracle with every hand visible and try to transfer its knowledge to a public-information policy. | **Tested recipes closed** | First aggregate `+0.073` was unstable across seeds; repaired shared-trajectory test was `+0.015`, lower bound `-0.067`; margin emphasis was worse. | These implementations did not transfer robustly. This does not rule out every privileged-information curriculum, but there is no authorized continuation now. |
| **H0** | **Human moves as proposals** | Add the human move to the search ballot and price it counterfactually rather than treating imitation as truth. | **No scientific result yet** | The only run completed 555 of 557 decisions. Two seven-card follow throws exposed a false candidate-enumerator assumption, so the predeclared all-or-nothing run published no aggregate. | This was a tooling failure, not evidence against human moves. Validate every candidate set before opening outcomes, then use a new population to compare human, model and equally wide random proposals. |
| **S6** | **Ballot sourcing** | Keep every legal throw visible, but spend extra search only on the late full-hand boss/near shape that repeatedly showed value. | **Selector passed reused-state screen; fresh preflight queued** | Exact-oracle value was `+0.234` levels (lower bound `+0.100`); the actor-visible selector realized `+0.307` (lower bound `+0.175`) and naturally triggered in 13/512 champion rounds. | Air will run the reviewed four-cluster preflight after its pair screen; a fresh whole-round treatment/null/champion test is still required before any strength claim. |
| **PAIR-ROLL** | **Pair-aware continuation** | Track which higher pairs have already disappeared so simulations can recognize when a low pair has become boss. | **Whole-game screen running** | Selected-root diagnostics favored the change on most finite-search disagreements, but points and level utility disagreed on one root. | The powered Air screen is the first whole-game strength read. Its result decides whether broad pair awareness, an attacker-only gate, or neither deserves another large run. |
| **PAIR-BALLOT** | **Retain legal pairs on the ballot** | Keep a legal pair from being crowded out before search can price it. | **Real, rare, defender-heavy gap; capacity design awaiting external review** | Census found 15,187 omissions across 18.6M SmartBot-trajectory leads (`0.0816%`), 97.6% early. The 1,024 selected rows are 1,023 defender and one attacker; the defender rows span 990 deal clusters. | Draft PR #72 at exact head `373de84` excludes the attacker, combines DEV+CALIB and binds exact membership/weights. Independent local builds on Python 3.11/3.12/3.14 are byte-identical after replacing version-sensitive `sum()` with `math.fsum`. External design review is pending; champion-natural dose is still required before whole-round inference. No preflight or run is authorized. |
| **S3B / S5** | **Exact endgames and defensive point protection** | Solve genuinely small endgames and stop avoidable point donations only when actor-visible play rules out a useful partner feed. | **Endgame mechanics bounded; S5 diagnostic execution HOLD after INC-18** | Four-card exact search exceeded its node limit. S5 replay found 58 strict hindsight triggers; only 16 still match today's rollout, and 57/58 already have a lower-point ballot action. The x86 portability construction PASSed, but its request template self-authorized a partial attempt and spent the one-shot admission without a result. | Start exact search at real two-card endings. For S5, first review the distinct-attestation repair; any recovery needs a new namespace and explicit retry marker. Only then run one final-champion diagnostic before designing a narrow no-partner-rescue treatment. Never generalize this to “never discard points.” |

### How to read a negative result

`SELECT_NONE` closes the exact policy, population and promotion claim that was
tested. It does **not** erase predeclared conditional evidence. Preserve
role/phase effects, trigger dose, tail failures and disagreement states as
labelled exploration inputs; they may justify a materially different gate or
model use, but never retroactively promote the failed policy.

The rollout work now forms one point-flow family: **S4** banks points while
winning, **S5** protects points while losing after the partner has acted, and
a future **ANTICIPATE_FEED** rule would model a partner or opponent feeding the
winner. Test them separately for attribution. If several survive, compare a
small named continuation-policy portfolio rather than silently bundling them.

<details>
<summary>Exact evidence identities and operational history</summary>

These hashes preserve auditability; they are not required to understand the
current policy conclusions above.

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
- Teacher Stage-C-v3 packet `f213314ace8ead497fcaccde150d0694851069b970948a10d0823cf74ceb93b4`
  led to externally replayed capture state set
  `c7a769c4efab582a38a4b77e8a707acde65a3e022d5db9fb27f660809e6e8e1c`.
  Label-v1 receipt `0c3d7ea00b2a0234102e11b46ef3bf5296437e4bd51418e048155c78693adc1c`
  remains terminal no-use. Corrected iid-v2 label aggregate
  `d0b4397ce0135b5ae665a76f9188ae3c974e2e440e0d6dc047d5080b27e6cdb9`
  supported first-generation training aggregate
  `7023b3aa08f399d582576b9998e5078db56d82a91eb2a41db228b4e2572fc4fb`,
  which selected none. Protected fresh-REPORT result
  `8fa323de3591f4665799225796299f0ccde97dcce0e191839b81ee7a1645aea6`
  also selected none. The distinct 7,040-state expansion is bound by reviewed
  label packet `82447501ca517d936fa5f453a793f0afae2dc05939d2088212746e75bc0e2084`.
  All 5,504 new labels completed with zero refusals and passed independent
  terminal review; aggregate
  `3deb3a81e31b898062d00762a6b8ec603acc4851531dfcbb5ed752b31304f6ca`.
  Frozen dataset `c24923f…a8382` and 96-cell packet `d137f31…71888` produced
  terminal aggregate `5ad77eb0…b6bd`. The whole-cohort selector chose the
  epoch-32 all-pairs bury ranker: 8/8 positive CALIB seeds and median
  candidate-zero improvement `+0.016418`. The direct candidate-zero loss did
  not win. External terminal review passed. Its v1 REPORT packet
  `5ce892db…25f0` consumed receipt `3c4b1f…74bf`, but all eight shard commands
  refused in argparse before evidence because `--expected-git` was absent.
  Zero labels/predictions/utility/results exist and the third population is
  closed. Externally passed successor selection `3c318da2…41e4` contains 512
  disjoint rows. Score-free v2 packet external/internal
  `e856c02e…175e2` / `96840fdb…82116` froze the 32 bury rows in eight shards;
  terminal result `2e21a9bf…ac4d` and final `126d73cd…e58387` were independently
  reviewed `SELECT_NONE`. The powered 219-state play exam likewise selected
  none: result `e2e774da…b4c5`, final `821c286b…f7c3`.
  The distinct trick-5+ protected-search successor used packet
  `017209a3…32f8`, selection `a79be3f6…a092`, aggregate
  `269eadf3…f2402` and result `f18c2e42…948f6`; its generated independent
  review marker is byte-identical at SHA-256 `6287ac4a…e97ace` and authorizes
  whole-game screen design only.
- S4 exact-state screen `abd9f36fa3e84c81b90e22f1c827f828a549f7fd6a9420ffbdb7c168974cdc00`;
  pre-outcome receipt `90124eb6f89c27cedc38770b2da5b3b8597400694281729656105f67803f526b`;
  admission `83993ec6609c2a7528853d4c1db789f137d3f0cbfff97d20fbf526cbd5ff5e6d`.
- S4 complete-round v2 preflight `fcc8b8913d80db5b1fe4bb7d6b727dc722bb7d0f4ec9c8806842535fc43ee060`;
  frozen packet `17036e6307ad0072ae10aeaaddde0ed3628a2f526ca440e909cdc35cd5071385`;
  consumed-screen admission `1d99bb55f780cb9f5a9f0ef99c810e0045eb99b458ff73d9190d8d59c60cbdbf`;
  receipt `20a420d2e939f8f1ce375ca32cee81d044db2c29dff7e52fbe7080a000dd65cc`;
  terminal aggregate `3c7f27b8466ec9ece73820d21d26349bfd95c4fc17db144b26408db4af6b4268`
  and supervisor final
  `e188f7e8ee80fe2fc17fee6d79b4eb4c6a41a45713c76825ef707981e30f2b24`.
- S4 independent replication packet
  `b239b8494e2f2ffa8fbc0a0b11b9b2f510d274dd6bb0a482e25fd87592cab76b`;
  receipt `fc6d54e7c3e660ee28fe96c16dd5babeb49856018b82e1aa309e640cdaf51077`;
  aggregate `d6b73f45c17f1b7ae6e1648147b82d248df82fd0f5b35a82a601108e8ba8f4d4`;
  final `20ece4eddcaa4399b45df768f4003b939a52c0346484924e3e05da9698af144a`;
  independent terminal-integrity review passed.
- Human H0 v1 design packet `9ff160a9bc54a30daa85a07b29440f5c4cdd1c8feb4574f81c102158e46247d3`;
  repaired v2 packet `2cccf5803ca60cf41690f18dc0e85febaf36a88ce702587e8c86a67e2a358f2b`;
  bounded v3 packet `4d3f0a35082c6957f2a468686b8eedbd6d7cbbf9540503fcea08cccf27c8cc3c`;
  bounded-v3 design-review marker `239f13ce52a8be81108fdebf9bd0e96742e60133`;
  reviewed corpus manifest `b9699790bdfe1c217922c9f9c72b237c1856174fa64c11753329a8ff11e16553`.
- H0-v3 controller v1 packet `13d9a97f9adf26860b9f5e0d4889960c75baa5bf979b939206d2399472ba61fc`;
  replacement v2 packet `3f68dc6ec6d5f90043f36c0a68847ca9ef510641e01760ac4fa11ebd6a6a7fcf`;
  candidate geometry `876ed56bd8f436d58cb6f3d58774a0f06756afb4d8c98ffdb49d9424b545ff2b`;
  v2 controller/runtime `108e6bb2…379` / `ddf8b250…a124`; external PASS
  marker is recorded at `cc1c293`. A later integration audit found that the
  consumed-slot file was unignored, so v2 cannot reopen after admission and
  has no execution authority. Replacement source `4ebcd09` / H0-v3 packet
  `cf074871cf977c0b072c528c395082b453b3b589f445c524baae9016e1d35392`
  passed externally at `205b6af`; its one execution terminally refused
  aggregate utility at 555/557. Preserved aggregate external/internal SHA is
  `84ef4400…196c` / `c314a2e1…6630`; partial utilities remain unread.
- S3a full-game aggregate `20609613e000ff4d11640dc35827527ca14e0ec09720c9c6cda1c64f6cdc271f`;
  terminal final `32156d79aaff247c2d3b60bcf45460442a224c31f415d6689b769b0eba32c9ff`.
- S3c census `236326099dc9763c6a5941bcb2a90670c4e23ac390ea07a0e4ec5063fa50b52a`;
  curriculum packet `df1024280a77c60174a57c3273ba3624e672bec9afde023576fde0404df49eca`;
  review marker commit `084ba7eba59cd0a317a50c4088f194d2376c1e03`;
  one-card controller packet `f58d23b74046dd04963b4f10fbf605030221219eef6d325c5e8319043643874a`;
  external component PASS marker is recorded at `cc1c293`. The same unignored
  consumed-slot defect blocks runtime. Replacement source `4ebcd09` / packet
  `cafbee439f8c30a07b0b6801d52620d7197afc3633badbc531bc5b156ce2f23e`
  passed externally at `205b6af`; one later mechanics receipt is eligible, but
  no solver work exists.
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

</details>

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
- Stage-C label v1 establishes a separate posterior rule: independent folds
  require domain-separated random streams, not unique realized deals. Repeated
  valid worlds must be retained with replacement; deleting within-fold
  duplicates or cross-fold overlaps changes probability mass and can exhaust
  finite late-state support even when every sampler call succeeds.
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

- **Kitty / S3a:** production is strongly point-shy. Structured point/void/trump
  candidates improved a selected-state objective, but the fresh complete-round
  screen selected none. Do not ship or retune that recipe; preserve its
  disagreements as Teacher and proposal diagnostics.
- **Point banking / S4:** changing only rollout continuation so a secure winner
  may bank a 5/10/K passed the exact-state mechanism test and the first
  2,048-cluster whole-game screen. The independent fixed replication stayed
  positive but selected none (`+0.048828`, LCB `-0.006884`). The exact recipe
  and both old populations are closed without retry, extension or deployment.
  A separately reviewed, disjoint 8,192/16,384-cluster sequential successor is
  running on Cloud; it accumulates only future evidence and never pools the old
  outcomes into its estimator.
- **Human evidence:** the repaired Fly corpus contains 2,830 plays and 45
  buries. Human actions are proposal and coverage evidence, not labels. H0-v3's
  sole counterfactual run completed only 555/557 rows, correctly published no
  aggregate, and cannot be retried or partially mined. That is an operational
  no-result, not evidence that human moves are weak.
- **Defensive point protection / S5:** seat-normalized log mining withdrew the
  original broad feeding headline. The reviewed score-free replay has now run:
  4,363 bot follows in 122 complete rounds yielded 58 strict hindsight DEV
  triggers, but only 16 are reproduced by today's candidate-zero/rollout
  surface and a lower-point action is already on the current ballot in 57/58.
  This localizes the surviving hypothesis to continuation choice/ranking, not
  broad sourcing. The census, PR #70 design and PR #74 portability construction
  are externally PASSed, but INC-18 consumed the one-shot admission in a
  partial request-self-authorized attempt and published no result. Its marker
  explicitly forbids retry. No treatment or strength result exists. Any
  recovery needs a distinct reviewer attestation, new namespace and explicit
  retry authority; any successor must use only actor-visible information, distinguish
  point protection from intentional partner feeding, and retain a matched
  null—not become “never discard points.”
- **Pair understanding:** the broad continuation hypothesis is already in a
  powered whole-game screen. PR #69 repair `ca1913f` now exercises the v1 parent
  and incremental cap on two separate leads because v3 returns early when v1
  fires; Claude's 22:36 review reproduced the two live actions and every
  mutation seam. A three-arm capacity design is now being built, not run.
  Pair-ballot omission is real but rare; its
  `0.0816%` prevalence comes from SmartBot trajectories, not champion-natural
  play. Draft PR #72 at exact head `373de84` combines its 1,023 defender rows
  across 990 deal clusters, excludes the lone attacker, and binds exact
  population/weight identity. Its generated capacity design is byte-identical
  on Python 3.11/3.12/3.14 after the `math.fsum` repair and has passed internal
  falsification; external design review is pending. Conditional utility still
  cannot be translated into whole-round gain until champion-natural dose is
  measured. No preflight or run is authorized.
- **Teacher Stage C:** the first 1,536-state, eight-seed generation selected
  none, and its protected play policy selected none on fresh REPORT. At 7,040
  DESIGN/CALIB states, the second generation selected a stable bury-ranking
  cohort: all eight seeds improved over candidate zero. The original all-pairs
  objective beat the direct candidate-zero loss, so data coverage—especially
  bury coverage—is the leading explanation. Its first REPORT execution failed
  in argument parsing before evidence and spent that holdout. A fourth
  zero-overlap 512-row population is selected score-free; the capability
  remains CALIB-only until a separately reviewed packet completes one valid
  32-bury-state look.
- **Shuai-pai / S6:** KESP showed legal early and late throws absent from the
  search ballot. Generic widening selected none, while a narrow actor-visible
  late full-hand boss/near selector retained strong reused-state value and
  naturally triggered in 13/512 champion rounds. Its reviewed Air preflight is
  queued behind the pair-aware screen. It still needs fresh capacity evidence
  and a treatment/null/champion whole-round screen.
- **People-facing target:** offline human agreement measures style and coverage.
  A challenger must first beat the live champion on paired bot games, then pass
  a separately consented and blinded HUMAN-C1 candidate-versus-champion test.
  Evaluation traffic remains physically excluded from training. The harness is
  intentionally inert until identity, receipt, consent, synthetic-C0 and
  estimator gates close.

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
