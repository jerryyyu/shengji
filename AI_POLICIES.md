# AI policy ledger

Last reconciled: **2026-10-16**.

**Production is release 46** (live 2026-10-16 14:49 ET, Fly v46): release 45 plus the v92 combo. Release 45 is the
rollback. **New screens still compare against release 45 as served** (Jerry, in-session 2026-10-13: "Yes change to
45", recorded on [#988 issuecomment-6142666693](https://github.com/jerryyyu/shengji/pull/988#issuecomment-6142666693);
it replaces the 10-07 release-42 ruling) until Jerry moves it (proposed: release 46 as served). Confirmations keep
their parent's comparator; screens already read keep their declared comparator.

This file holds the callable-policy contract and the scientific conclusions that constrain policy work; it is not a
run log or a copy of the registry. History lives in Git and `docs_archive/`; do not append dated status blocks. The
long-form text this file carried until 2026-10-16 is verbatim in
[docs_archive/ai-policies-detail-through-r46-2026-10-16.md](docs_archive/ai-policies-detail-through-r46-2026-10-16.md)
("the detail archive" below).

## Production contract

Release 46 is the `pv-search` policy/value search, W64/K8, no playouts. Rule tokens (and the release that added
each) are in parentheses; rules are off by default in source and on in production (#676).

| phase | stage | budget and fallback |
|---|---|---|
| declare | The heuristic proposes. At every first-round chance with an option (`vdef`, 46), else where the heuristic would declare or in the grace window, the value head scores each legal declaration plus PASS over 64 sampled completions (heuristic bury and first trick inside) and replaces the heuristic only when beaten (`vd`, 44; #952, #959, #958, #965). | Off the event loop on copies, applied only if the round is unchanged; heuristic on expiry or error; a human's declaration wins any race. |
| bury | 64 candidates (the hybrid ballot plus the incumbent's single-card swaps), chosen by the value head's mean over the arm's model worlds; no MC stage (`bwv` K=64, 45; #974). | 2 s; heuristic fallback. |
| play: worlds | 64 worlds, history-legal (`whl`), drawn under the pair obligation (`whd`), hidden hands proposed by the S17 belief model (`bw`) (46); this round's refused throws stay refusable with the same forced component (`rc`, 38; #689). | A belief error, including preparation over 0.25 s, falls back for that decision to the history-legal draw and is recorded. |
| play: admit | Policy head admits 8: at most 2 per structural key, near-duplicates skipped, back-fill (`div`, 38; #680); on a lead whose heuristic anchor is a non-trump single that is not the top live card, slot 0 is the highest plain pair/tractor, else the policy's top action (`la`, 38; #694). | 3 s per play; on expiry, the heuristic anchor. |
| play: price | Value head prices each afterstate in each world; within 0.02 level of the best mean, most root-team points from the current trick wins (`tb`, 38; #682). | |
| play: doomed throw | A lead the engine refuses in every world with the same forced component is excluded with that component; the bot re-selects (`dtr`, 43; #946, replacing 42's swap `dts`, #830). | Abandonment keeps the first selection; all excluded plays the forced component. |
| play: ≤ 7 cards | Lead with > 1 candidate: exact level-mode minimax per world after the first-trick leaf (`ele`, `ed7`). Follow: exact re-rank on the compiled compact-level solver, 50M nodes (`xf7`, `xfcompactlevel`) (46; #1066). | Inside the 3 s; expiry or error keeps the baseline choice. |

**Packages:** play/value `smv3out-491ee4bf` (gen-5 SMV3 outcome head, since release 36); prior keys JS-M1 `0d17fd03`
(since 28); belief NumPy `s17long-e2-763b5e05`, sha-pinned, loaded once per process. **Logging:** the belief log is on
by default (#1068): each play record carries `belief_seed` and a marginal snapshot; no decision depends on it.

Served name, package SHA256s, `fly.toml`, deploy record and rollback: `DEPLOY.md` "Current production" and the
Releases table; the registry derives the name from that environment, never by hand. Changing the package, world
count, admitted-candidate count, cap, sampler, belief package, exact-stage limits, rules or bury arm makes a new
policy and needs fresh evidence. Every deploy passes `DEPLOY.md` "Release checklist". The release-38 contract and its
release-era subsections are in
[docs_archive/ai-policies-release-sections-through-r38.md](docs_archive/ai-policies-release-sections-through-r38.md)
("the release-era archive").

## Before the ladder

The baselines every result is read against (names from `server/shengji/ai/registry.py`):

- **SmartBot** (`smart`): the public-memory heuristic. Its pick is the incumbent, candidate zero, in every search.
  The stateless `heuristic` is the rollout policy inside Monte Carlo.
- **MC strong** (`mc-strong`): determinized Monte Carlo, N=30 worlds, heuristic rollouts, argmax that overrides
  SmartBot's pick only by a 5-point margin. Production before MC-LCB. Siblings differ in world count: `mc-lite` 5,
  `mc` 10 (the source fallback), `mc-vstrong` 60 (no further gain).
- **MC-SmartRoll** (`mc-smartroll`): `mc` with SmartBot rollouts, ~5× slower. Never screened as a production
  candidate; a 4-world variant opposed the first policy/value pilot and proved weaker than MC-LCB.
- **MC-LCB** (`mc-s0-report-lcb`): `mc-strong`'s 30 worlds nominate one challenger; challenger and incumbent replay
  on R=300 fresh shared worlds, and the challenger plays only if its one-sided paired lower confidence bound is ≥ 0.
  Production until 2026-09-08; now the rollback/reference policy and **the common control for every screen**.
- **The W32 shortlist** (`mc-shortlist-*`, releases 22–28): the value net ranks every legal action over 32 worlds and
  4 alternatives plus the incumbent go to MC-LCB's search; release 27 added a policy prior, release 28 merged both
  into one package, **JS-M1**.

**Reading the ladder.** From release 29 each row is one screen: the candidate and the release it replaced each play
the same fixed MC-LCB control on the same deals (ten 520-cluster mirrored windows unless noted), and the result is
the difference in signed levels per round. Rows are separate contrasts from different eras: **not one calibrated
scale, not additive.** Rows before 29 used other instruments. Fresh-seed confirmation ran only where Jerry or the
packet required it.

## The ladder: every production change and what it measured

Newest first; rows 7–15 (release 29 up) are the README's "Served results by release" plot plus the correctness
fixes. Row numbers are stable; other documents cite them.

| row | rel. | change (token) | vs | result [95% CI] | status | reading | pointer |
|---:|---:|---|---|---|---|---|---|
| 15 | 46 | belief worlds (`whl whd bw`) + exact endgame D7/X7 (`ele ed7 xf7 xfcompactlevel`) + `vdef` | 45 | **+0.2167 [+0.1923, +0.2412]**; v92c **+0.2284 [+0.2046, +0.2521]** | POSITIVE, CONFIRMED | Three changes at once; the largest served gain. | v92combo45 #707 issuecomment-6216352632; v92c 6221702452 |
| 14 | 45 | wide value-only bury, K=64 (`bwv`) | 44 | **+0.0488 [+0.0286, +0.0690]** | POSITIVE | One screen; width and chooser changed together. | v76bwv44 #707 issuecomment-6136852119 |
| 13 | 44 | value-guided declaration (`vd`) | 43 | **+0.0497 [+0.0379, +0.0615]** first-round; **+0.0352 [+0.0233, +0.0471]** later-round | POSITIVE | First decision owned beyond card play; 20/20 windows positive. | v70vd43, v71vd43lr |
| 12 | 43 | doomed-throw re-select (`dtr`) | 42 | −0.0004 [−0.0122, +0.0114] | spans zero: correctness fix | Re-selects the best remaining lead instead of the forced component. | v67dtrg #707 issuecomment-6080113005 |
| 11 | 42 | doomed-throw swap (`dts`) | 38 | −0.0002 [−0.0102, +0.0099] | spans zero: correctness fix | Failed bot throws −64%; replaced in 43. | v57dts #707 issuecomment-6026001554 |
| 10 | 38 | search rules `div` + `rc` + `tb` | 36 | **+0.0461 [+0.0242, +0.0681]** | CONFIRMED | Only in combination; each alone unconfirmed or inconclusive. | combo2 #676 issuecomment-5962364713 |
| 10 | 38 | + lead anchor `la` | div+rc+tb | +0.0106 [+0.0006, +0.0205] | POSITIVE (incremental) | Lower bound near zero; not a second confirmation. | v43cla #676 issuecomment-5965252288 |
| 9 | 36 | SMV3 outcome head (`491ee4bf`) | 30 | **+0.0393 [+0.0033, +0.0752]** | CONFIRMED | Gen-5 head, search unchanged; five windows, predeclared second read. | v36a2 (first read v36a), #663 |
| 8 | 30 | hybrid-bury fix | 29 | not measured | correctness fix | Ended silent heuristic fallback on ~6% of banker burys. | #607 (#606) |
| 7 | 29 | policy/value search, soft head (`pv-search` W64/K8) | 28 | **+0.049 [+0.003, +0.095]**; card play **+0.086 [+0.042, +0.131]** | POSITIVE | Policy admits, value prices, no playouts; five windows. | v34pv; #553, #588 |
| 6 | 28 | JS-M1 as one package | 27 | +0.006 [−0.016, +0.028] | spans zero: cost | One file is both prior and value net. | release-era archive |
| 5 | 27 | policy prior v2 | M1, paired | −0.0003 [−0.0017, +0.0012] | spans zero: cost | Bounds the tail above 1,000 legal actions. | release-era archive |
| 4 | 25/27 | M1 value net | release-24 package | **+0.021 [+0.004, +0.039]** | CONFIRMED | The one confirmed model gain of the shortlist era. | release-era archive |
| 3 | 22 | hybrid bury | heuristic bury | **+0.036 [+0.012, +0.060]** utility | POSITIVE | Research recipe; the served 2 s budget and fallback were not measured. | [bury report](docs_archive/value-guided-bury-dev-2026-09-08.md) |
| 2 | 22 | W32/K4 shortlist | MC-LCB | **+0.139 [+0.065, +0.217]** | POSITIVE | First learned win: model picks what to search, MC decides. | release-era archive |
| 1 | pre-22 | MC-LCB report rule | `mc-strong` | **+0.338 ± 0.068** | CONFIRMED | The rule, not extra search: matched null −0.019 ± 0.068. | release-era archive |

**Notes** (everything else is in the detail archive, `DEPLOY.md` and Atlas v2):

- **46.** Components alone, never pooled: belief v86bw45 +0.1165 [+0.0914, +0.1416]; D7 + X7 v89dx7 +0.0439
  [+0.0307, +0.0570]; `vdef` v85vdef45 +0.0220, confirmed by v85c +0.0421 [+0.0252, +0.0590]. Banker share 71.4% vs
  51.9%, so the points margin is role-confounded. Belief fallbacks 0 of 356,238 records. Latency v93lat QUALIFIED:
  play p95 0.187 / p99 0.400 / max 2.404 s vs 0.154 / 0.177 / 0.348 s, peak RSS +48 MiB (#707
  issuecomment-6221489445). First-round deals only. Deployed via #1072 (main `ab6fd1b2`).
- **45.** Not confirmed on fresh seeds (Jerry shipped on the screen). Banker share identical (52.3%); the gain is in
  defending the bank (+1.309 points/round [+0.877, +1.741]). First-round deals only.
- **44.** First-round and later-round deals are separate populations, never pooled. On release 42: v68vd42 +0.0475,
  v69vd42c +0.0590 CONFIRMED.
- **42, 43.** DEPLOY-ELIGIBLE means not demonstrated negative, NOT noninferiority; harm of about −0.01 stays
  compatible.
- **38.** `la` alone +0.0138 [+0.0013, +0.0262] (five windows, exploratory).
- **36.** First read v36a +0.0361 [+0.0015, +0.0707]. The policy head alone beats the production head by +0.21 in
  paired duels while served head swaps sit within ±0.02: decoupling, not a ceiling (#663).
- **29.** Vs MC-LCB the search wins at W16–W64 (W64/K8 +0.187 [+0.144, +0.231]); W4 loses. The served read is a
  common-opponent summary-level estimate, not paired inference.
- **27–28.** JS-M1's owed fresh-seed read was −0.0159 [−0.0383, +0.0065] vs release 27, so 28 has no strength claim.
  M1 on fresh deals: +0.0212 [+0.0036, +0.0387].
- **22.** W32/K4 cost 3.53× wall, engineered to 2.849× bit-identically.

## Tried and not taken

Newest first; ten-window screens vs the named release as served unless noted, each read once and archived under
`~/shengji-archive/2026-09-13/readouts/`, with an Atlas v2 row. Inconclusive is not equivalence.

| change (vs) | read [95% CI] | why not taken | pointer |
|---|---|---|---|
| D6 + X6 exact endgame alone (45) | v87dx45 +0.0384 [+0.0278, +0.0491]; v87c +0.0345 | Superseded by D7 + X7 in the release-46 combo. | #707 issuecomment-6203794263; #1065 |
| declaration wait option `vdw` (45) | v82vdw45 −0.0003 [−0.0017, +0.0011] | Inconclusive. | Atlas v2 |
| two-stage bury scorer `bts` (45) | v81bts45 +0.0044 [−0.0035, +0.0123] | Inconclusive. | Atlas v2 |
| declare-ASAP instead of `vd` (45) | v80decl45 −0.0056 [−0.0236, +0.0124] | Inconclusive; `vdef` taken instead. | Atlas v2 |
| served bury inside the value declaration (45) | v79vdsb45 −0.0045 [−0.0084, −0.0007] | Resolved negative. | Atlas v2 |
| two-card bury swaps, K=128 (45) | v77bwv2r45 −0.0036 [−0.0088, +0.0016] | No gain over K=64; bury cost doubled. | Atlas v2 |
| policy-head first trick in the value leaf `lpft` (44) | v75lpft44 −0.0061 [−0.0145, +0.0022] | Inconclusive; not pursued. | #972 |
| model-free declare-ASAP `asap` (43) | v73asap43 +0.0507 [+0.0320, +0.0695] | `vdef` shipped instead; causal reading corrected. | #707 issuecomment-6117945099 |
| C12: rank-regret e8; + wide lead admission; val_ce e16 (42, five windows) | −0.0130 [−0.0458, +0.0198]; −0.0107 [−0.0480, +0.0266]; −0.0131 [−0.0437, +0.0174] | No demonstrated gain; C12 closed. | v63c12r/rwla/v; #663 issuecomment-6119248471 |
| adaptive worlds (42) | v61aw42 +0.0217 [−0.0048, +0.0482]; v62aw42c +0.0029 [−0.0257, +0.0315] | Not confirmed on fresh seeds. | #707 issuecomment-6057209540 |
| SMV3-SL4, rollout value labels (36) | v40a −0.0162 [−0.0600, +0.0275] | Inconclusive. | #663 |
| adaptive K16 on multi-card leads (36) | −0.0061 [−0.0303, +0.0181] | Inconclusive. | v41ak #676 issuecomment-5963808991 |
| PUCT on the SMV3 package (36, five windows) | package prior −0.417 [−0.463, −0.371]; uniform −0.894 [−0.928, −0.861] | Unpaired one-world-per-visit noise; closed. | #436 issuecomment-5962752743 |
| root-allocation pilot A6 (24 DEV roots) | — | Closed. | #436 issuecomment-5962069171 |
| search-mean head as the value function (30) | v36b −0.0523 [−0.0905, −0.0140] | Resolved negative. | #663 step 4 |
| more worlds beyond 64 | W128−W64 +0.024 [−0.034, +0.083]; W256−W64 +0.024 [−0.033, +0.081] | No gain resolved. | Atlas v2 |
| K16, bounded PUCT, learned continuations, adaptive allocation | each failed to clear zero vs its parent | No gain at large cost. | scaling page |
| warm-started generations as shortlist packages | v33 −0.007 [−0.038, +0.024] | Instrument ties 54–62% of deals. | release-era archive |

**Gen 5 retrains (2026-09-24 to 09-27).** Five one-variable retrains of the production head vs release 30, five
windows each (MDE80 ≈ 0.05): dropping the MC-LCB corpora was resolved negative (arm A −0.061 [−0.096, −0.025]);
restoring them, all corpora (496k deals), a warm start and the #649 policy-target units fix spanned zero (B +0.012,
C −0.003, D −0.018, F +0.010). Corpus volume, composition, warm start and policy targets are not levers at this MDE:
the served search uses the policy head only to admit, and the value head decides (#649, #650, #658).

**Exploitability, not established (#625, closed 2026-09-28).** Reweighting the search's 64 worlds by an opponent
model's likelihood of the observed plays is harmful: −0.249 [−0.273, −0.225] vs SmartBot. The opponent model was
right; the posterior collapsed to ~2 of 64 worlds and variance swamped candidate margins. A best response needs the
opponent inside the rollout continuation.

## Callable policy families

If this summary and `server/shengji/ai/registry.py` differ, the registry is authoritative.

| family | intended use | status |
|---|---|---|
| `heuristic` | Stateless legal baseline and stable Elo anchor. | Supported baseline, not production. |
| `smart`, `smart-v1`, `smart-v2` | Public-memory heuristics: card counting, boss/void inference, point flow, safe throws, ruff risk, bury and endgame rules. | Supported baselines and rollout policies; lineage stays source-bound. |
| `mc`, `mc-lite`, `mc-strong`, `mc-vstrong` | Determinized Monte Carlo at named work levels; `mc` is the source fallback, `mc-strong` (N=30) a historical rollback. | Supported. A legal sampler is not a calibrated belief model. |
| `mc-s0-*`, nulls, prefix policies | Frozen search/report experiments and matched controls. | Experiment/reproduction only unless `fly.toml` names one. |
| structured-bury, exact-endgame, point-banking, pair/throw and ballot variants | Mechanism-specific constructors; some stay outside the global registry to preserve evidence identity. | No production authority. |
| learned checkpoint policies (`rl`, V11, teacher, Direct-Q and successors) | Offline diagnostics, bounded proposals/rankers, or reviewed experiments. | Lazy/opt-in only; production serves only the `pv-search` package. |
| `mc-cwv-<ckpt8>-w<W>`, `mc-cwv-prior-<ckpt8>-w<W>` | One-ply search whose ENTIRE evaluator is the complete-world value net (`ai/cwv_policy.py`): production's ballot and sampler, every (candidate, world) afterstate over W worlds scored in one batch, argmax of the mean. The `prior` twin is the no-learning control (the training receipt's stratified prior as the value, in its own utility scale: PT0 integer levels for the `baselines` prior, exact terminals converted to match). Registered by `register_cwv_policies` or `SHENGJI_CWV_CKPT`; the checkpoint id is in the name, and a checkpoint whose encoder identity differs from `value_afterstate`'s is refused. | Dev screen only (`scripts/cwv_duel.py`, budget ladder 1x/3x/10x of production's wall). No strength claim; no production authority. |
| `mc-s0-report-lcb-x3`, `-x10` | MC-LCB with selection and report doses scaled together (N=90/R=900, N=300/R=3000): its own compute curve, the bar a learned arm must beat at each budget. | Reference arms only. |
| `mc-shortlist-<ckpt8>-w<W>` (`CWVShortlistBot`) | Every legal action ranked by the complete-world model over W worlds; K4 or K8 alternatives plus the incumbent go to full N30/R300 MC, so unlike `mc-cwv-*` the model does not replace the final evaluator. Registered by `register_cwv_shortlist_policies` or `SHENGJI_CWV_SHORTLIST_CKPT` so `make_bot` and `harvest/trajectory.py --policy` reach it; the entry point refuses anything that is not a `CWVShortlistBot` (`mc-cwv-<ckpt8>-w32` is the one-ply bot). | Production 22–28 (W32 play, hybrid bury, bounded heuristic fallback); since 29 a registered rollback (its keys stay in `fly.toml`). |
| `pv-search-<ckpt8>-w<W>-k<K>[-<rule tokens>]-r<recipe8>[-bury-hybrid-<id>]` (`PVSearchBot`, `PVSearchBuryBot`; `train/pv_search_policy.py`) | The policy/value search and its bury on the same package; registered by `register_pv_search_policies` when `SHENGJI_PV_CKPT` and `SHENGJI_PV_SHA256` are set, name derived from the environment. | PRODUCTION since 29; release 46 is the [production contract](#production-contract). |

Local: `SHENGJI_BOT=smart uv run shengji-server`. In code, always pass a deterministic seed:
`make_bot("mc-strong", seed=1234)` (from `shengji.ai.registry`).

## Search and heuristic behavior that survives

Governing conclusions only; old toggle grids are in Git history and their head-to-head rates are screening evidence.

- N=30 Monte Carlo clearly improved on the smaller base search; uniform N=60 did not. The conservative disjoint R=300
  report fold is the confirmed improvement; other confidence and allocation recipes added no winner.
- The heuristic incumbent remains candidate zero. Tractor-lock, point-shy near-tie handling, deterministic ballot
  order and exact work counters are policy identity.
- Public memory may use declarations, plays, voids, remaining-pair/run bounds, the actor-private hand, and the
  banker-private burial where applicable; never other hidden hands or a non-banker burial.
- Heuristics (safe-shuai, boss/pair/tractor, point flow, ruff risk, void building, endgame) are parents and
  diagnostics, not proof that every fallback is strong. Before patching a production quality gap, replay it and
  attribute it to legality, ballot, world sampling, continuation or value.

## Scaling and search insights

As of 2026-10-16; runs are on the scaling page (`docs/scaling_log/`), the search atlas and Atlas v2.

- **Offline loss does not order play.** The best CE played like the leader; the last shortlist data doubling bought
  −0.0036 CE and nothing in play; width and depth alone, DEEP8 and TOWER1 did not confirm. Encoder v2 was the one
  real encoder gain (v3–v5 nothing); warm-started generations were null as packages.
- **A better head alone is not a better served bot.** The head alone went from SmartBot-level (soft +0.052 [+0.039,
  +0.067]; JS-M1 −0.0137 [−0.0269, −0.0004]) to +0.24 vs SmartBot after the #649 fix, and SMV3's head beats the
  release-30 head by +0.21 in a head-only duel that sees the true hands; the served gain was +0.0393.
- **The soft target** (the search's own values) is the training ingredient with the largest point estimate.
- **The value head replaces playouts**; a T1 value cutoff beats terminal-level MC.
- **World quality, not world count.** Gains stopped at 64 worlds (offline 512 vs 64 −0.0007 [−0.0022, +0.0008] per
  decision); belief worlds gave +0.1165 (board S2, D6).
- **K8, not K16.** Learned continuations and bounded PUCT lose or add nothing at large cost; any tree search keeps
  candidates on paired worlds (RL_PLAN "Search and teacher strategy" item 4).
- **Exact search pays in small endgames**: D7 + X7 +0.0439 alone.
- Release 29's served read (+0.049) is below its card-play read (+0.086) with no measured cause; the deploy gate is
  the served design. Corpus seeds are decks and are excluded from screens per model.

Superseded since the 2026-09-22 version: "no head in the W64 family is shown superior" (contradicted by v36a2 and
by C11 epoch 9 over epoch 6, v54ep9c +0.0455 [+0.0079, +0.0831]); "worlds were the lever through 64" (it is world
quality); "learned continuations lose" (the exact endgame continuation wins at ≤ 7 cards).

## Current scientific conclusions

- **Belief worlds are the biggest served gain** (v86bw45 +0.1165 alone); search is belief-limited.
- **Components are not additive; the combo read is the decision.** Belief, D7 + X7 and `vdef` (+0.0421) were read
  alone, and `vdef` changes who banks (71.4% vs 51.9%), so release 46 was screened and confirmed as one policy.
- **DEV head-to-head duels run several times larger than screens:** `vdef` vs release 45 +0.115 [+0.060, +0.175]
  (200 DEV deals) against screens of +0.0220 and +0.0421; D6 + X6 double-dummy +0.256 [+0.170, +0.352] against
  +0.0384; S18 +0.064 against +0.0071 (board S26, S29). DEV bars rank lanes; the screen decides.
- **Value noise is not the lever.** More evaluations on the same worlds (adaptive worlds, W > 64) did not confirm;
  better worlds (belief, history legality) did.
- **Model-owned decisions move the result** where heuristics decided: declaration (44, `vdef` in 46) and bury (45).
  Successors: RL_PLAN "Planned work".

**Retired lanes** (full entries in the detail archive). None cleared a registered whole-game bar; reopen only on a
materially different axis, never as an unchanged or larger retry: global learned rankers, V11, Direct-Q and teacher
direct play (label fit did not transport); S4 point banking, S6 shuai sourcing, pair-aware continuations; T4 model
proposal (its widening control used 14.8% more worlds and 80.9% more searches, so it needs a three-arm attribution
test); BELIEF R4/R5 (the 21.40% Brier gain also appeared under permuted labels; `NO_PRIMARY_POLICY_SIGNAL`;
unrelated to the S17 belief served in 46) and the BELIEF V1/R3 resource failures (no learning verdict); privileged
teachers PT0 (small edge), PT1 (`1/208` mean C−B, with a governance caveat) and PT-Full (preserve posterior
ensembles); C0; the shortlist K8 (+0.08203 vs production, −0.05664 vs K4); Value-Afterstate V0
(`REFUSE_MECHANICS_OR_NEGATIVE_CONTROL`) and V1 P1 (`SELECT_NONE_NO_ACTION_ADVANTAGE`); the PT-Sol0/PT-Luna
planners (open-DEV mechanism evidence; batch4−compact1 −0.1058 [−0.2885, +0.0769],
[readout](server/runs/luna_quality_gameplay_tranche1_result_20260906.md)); Value V2 D64 (`D64_DEV_SEALED`: shape
improved, scalar and action value worsened).

## Evaluation and identity rules

Every decision-bearing policy comparison binds:

1. exact source, policy names/classes, engine/native mode, and runtime;
2. ballot and incumbent identity;
3. sampler, continuation, objective, perspective, and deterministic seeds;
4. selection/report budgets and exact accepted-work counters;
5. mirrored roles/deals and the round/deal cluster as the uncertainty unit;
6. immutable population, split, artifact schemas, and terminal rule; and
7. a behavior/work-matched null that differs only on the proposed mechanism.

Elo pools, human agreement, individual decisions, offline loss, state regret and open-DEV screens prioritize
hypotheses. Strength requires a fresh mirrored whole-game comparison against the exact live champion. Confirmation is
Jerry's call per change (2026-10-13, in-session; recorded on
[#663 issuecomment-6142998363](https://github.com/jerryyyu/shengji/issues/663#issuecomment-6142998363)): a
positive screen can ship on his word, and a fresh-seed confirmation runs when he asks or when the effect is small
or borderline.

## Entry criteria for new scientific lanes

Moved from `BACKLOG.md` on 2026-10-03. A proposed lane enters the review queue only when it names:

1. the exact decision or prediction it changes;
2. the natural dose and the smallest effect worth detecting;
3. the candidate, the literal parent, and a behavior/work-matched null;
4. one frozen population/split and one terminal rule;
5. source, runtime and artifact identities, plus recoverability behavior;
6. one consolidated review surface; and
7. for any projected multi-hour run, one pre-launch DAG audit that proves there is no duplicate full-data
   integrity work, names worker/core utilization for every expensive stage, demonstrates checkpoint/recovery
   behavior, and identifies the cheapest learning-bearing result before fleet scale.

Run a cheap score-free census or rehearsal first when dose, runtime or candidate geometry is unknown. A rehearsal
proves mechanics, not efficacy; the rule that nothing scientific (seeds, thresholds, populations, terminal rules)
may be chosen from one is under [Change and deployment rules](#change-and-deployment-rules).

## Correctness and runtime boundaries

- Tied effective cards retain physical identity. Throws may be ruffed. Failed throws force the engine-selected
  component. Pair and follow obligations are engine facts, not heuristic preferences.
- The current sampler consumes public declarations, voids, remaining-pair/run bounds, hand sizes and actor-known
  burial once. Strict validity/support on named reservoirs does not prove posterior calibration or globally complete
  constructive dealing.
- Banker declaration pins must allow a declared card to be in the hidden burial when the rules permit it. Public
  failed-throw content is limited to what the engine actually broadcasts.
- `SHENGJI_FAST=1` routes through reviewed native kernels. Pure/compiled parity and bit identity are correctness
  gates; a speedup is not strength evidence.
- Production does not enable experimental posterior-changing sampler flags. Release 46's history-legal,
  belief-proposed worlds are the one posterior-changing sampler in production, admitted by its screen, confirmation
  and latency gate (ladder row 15).
- Factory seeds must reach every stochastic component. Caches use canonical keys and defensive copies. Inside
  scientific packets, short/zero-work evaluations refuse rather than silently fall back.
- Encoder identity includes semantics and transitive source bytes. Assets with private-kitty or other
  actor-visibility drift remain quarantined even when their tensor dimensions match.

## Operating constraints

Moved from `BACKLOG.md` on 2026-10-03.

- No test opening before a durable pre-test readiness artifact proves that training, calibration, curves and exact
  identities independently reopen.
- Expiry yields a sealed, explicitly truncated result at the best complete common epoch when the design permits it.
  It must not erase healthy learning or masquerade as convergence.
- Preserve reusable capture, reference, index, cache, checkpoint and calibration artifacts when their contracts
  permit exact reuse.
- Progress must expose completed/total units, percent, elapsed time, ETA, stage, worker identity and deadline
  headroom without exposing outcomes.
- Use diverse trump ranks and player/deal-disjoint human data. Human moves are behavior/proposal evidence, not
  strength labels.
- Keep facts, actor-private observations, probabilistic beliefs and privileged labels typed and separate.
  Actor-visible runtime bytes must be invariant to hidden-world twins.
- Negative and refused results remain evidence. Never delete them, retry a spent namespace, or convert a mechanism
  PASS into deployment authority.
- `HANDOFF_REVIEW.md` is closed: it has taken no markers since 2026-09-03 (#674). Grep it for a marker name rather
  than reading it whole. Verdicts live in PR review comments; chronology and current review asks on GitHub issues.

## Change and deployment rules

- Name the literal parent; “current,” “MC,” and “champion” are not identities.
- Review scientific source/freeze once, as one packet. Add another review only when the first finds a load-bearing
  defect or reviewed bytes materially change.
- Never use a rehearsal outcome to tune a frozen population, threshold, seed or terminal rule. Rehearsal proves the
  mechanics path only.
- Correctness fixes, throughput gains, larger corpora or better training loss enable a policy experiment; none
  counts as an AI win.
- No result may implicitly authorize merge, promotion, deployment, retry, test opening or a different policy. Those
  authorities are explicit and separate.

## Durable pointers

| topic | source |
|---|---|
| current queue and priority | GitHub: the board issue #707, open issues and PRs (`BACKLOG.md` was deprecated 2026-10-03 and is a pointer stub) |
| active fleet, open investigations and exact review asks | `server/scripts/fleet_status.sh`, the board issue #707 (its predecessor #679 is closed and holds everything finished through 2026-10-03) and its topic issues (#663 model, #700 gameplay audit and search diagnostics, #676 search screens, #436 PUCT/allocation, #681 lead audit; the Sol benchmark #355 is closed), and the owning GitHub issue or PR (`HANDOFF_ACTIVE.md` was deleted, #674) |
| callable code | `server/shengji/ai/registry.py` |
| production config | `fly.toml` |
| model/belief/teacher design; research architecture and model lineage | `RL_PLAN.md` |
| immutable evidence and review corrections | `HANDOFF_REVIEW.md` authority markers (frozen to its markers, #674; verdicts and reviewer corrections are PR review comments; prose lives on GitHub issues; archived text in `docs_archive/handoff-review-*.md`) |
| engine/sampler contract | `server/tests/`, `incidents/` (ledger archived at `docs_archive/correctness-through-2026-09-22.md`) |
| performance and deployment | `DEPLOY.md`, issue #208 (the speed record is archived at `docs_archive/perf-through-2026-09-22.md`) |
| what each production change bought | [the ladder](#the-ladder-every-production-change-and-what-it-measured) |
| screen results since release 29 | `docs/atlas_v2/registry.json` (Atlas v2) |
| agent execution discipline | `AGENTS.md` (the daily routine is archived at `docs_archive/maintenance-through-2026-09-22.md`) |
| old policy/toggle ledger and long-form detail | Git history, `docs_archive/`, and [the 2026-10-16 detail archive](docs_archive/ai-policies-detail-through-r46-2026-10-16.md) |
