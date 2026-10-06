# AI policy ledger

Last reconciled: **2026-10-06**.

**Production is release 42**, live since 2026-10-06 19:08 ET: release 38 (release 36's package, the gen-5 SMV3
outcome head, in the release-30 pv-search W64/K8 + hybrid bury, plus four search rules) with the doomed-throw swap
`dts` on. Jerry set **release 38 as served** as the comparator for new screens on 2026-10-03; that new screens
compare against release 42 as served is proposed, pending his confirmation. Screens already read against release
36, the combo or release 38 keep their declared comparator.

This file holds the callable-policy contract and the scientific conclusions that constrain policy work. It is not a
run log or a copy of the registry. Other sources are under [Durable pointers](#durable-pointers). History lives in
Git and `docs_archive/`; do not append dated status blocks here.

## Production contract

What is served is release 42: the `pv-search` policy/value search (the package's policy head admits 8 of the legal
actions over 64 sampled worlds, its value head prices their afterstates, no playouts), value-guided hybrid bury on the
same package, budgets 3 s play / 2 s bury, the JS-M1 prior keys retained from release 28, and four search rules that
are off by default in source and on in production (#676): admission diversity `div` (#680; at most 2 admitted
actions per structural key, near-duplicates skipped, back-fill when short), refusal-constraint sampling `rc` (#689;
sampled worlds must make this round's refused throws refusable with the same forced component), tie-break by points
`tb` (#682; among candidates within 0.02 level of the best mean, the most root-team points from the current trick)
and the lead anchor `la` (#694; on a lead whose heuristic anchor is a non-trump single that is not the top live card,
slot 0 becomes the highest plain pair/tractor, else the policy's top action), plus, since release 42, the
doomed-throw swap `dts` (#830; on a lead whose throw the engine refuses in every sampled world with the same forced
component, play that component instead). On budget expiry the bot plays the
heuristic anchor. The served bot name, package SHA256, `fly.toml` environment, deploy date, rollback steps and the
earlier releases are in `DEPLOY.md` ("Current production" and the Releases table); the registry derives the name from
that environment and it is never hand-written. Changing the package, world count, admitted-candidate count, cap,
sampler, rules or bury arm makes a new policy and needs fresh evidence (ladder rows 10 and 11 for the rules, row 9
for the package). The release gate every deploy must pass is `DEPLOY.md` "Release checklist". The release-era subsections
this file used to carry (policy prior admission, the soft head, JS-M1, serving qualification, hybrid bury
integration, `mc-s0-report-lcb`) are archived verbatim in
[docs_archive/ai-policies-release-sections-through-r38.md](docs_archive/ai-policies-release-sections-through-r38.md).

## The ladder: every production change and what it measured

Each row is measured **against the policy it replaced**, on that era's instrument, in signed levels per round unless
noted. The numbers are NOT additive and NOT on one scale (opponents, deals, designs and budgets differ by era): a
chain of relative reads, not a cumulative total. Seven of the eleven changes measured a resolved gain; four shipped for
cost, maintainability or correctness with no strength claim. Row 10's confirmed part is the three-rule combination;
its lead-anchor increment is a small positive read, not a confirmation.

| # | change | what it replaced | measured effect | instrument | reading |
|---:|---|---|---|---|---|
| 1 | **MC-LCB report rule** (`mc-s0-report-lcb`) | `mc-strong` N=30 argmax | **+0.338 ± 0.068** | 2,048 fresh clusters | The one-round nominate-then-confirm rule, not extra search: the matched extra-work null was −0.019 ± 0.068. |
| 2 | **W32/K4 shortlist** (release 22) | MC-LCB alone | **+0.139 [+0.065, +0.217]** | 256 rank-2 deals, paired | The first learned win: the value net chose what deserved search, the search still decided. 3.53× wall, engineered to 2.849× bit-identically. |
| 3 | **Hybrid bury** (release 22) | heuristic bury | **+0.036 [+0.012, +0.060]** utility | 1,976 fixed deals | Model-scored heuristic candidates, MC selection. The trial was the RESEARCH recipe, with no deadline and no fallback; the deployed arm adds a 2 s cooperative budget and heuristic fallback, and that serving modification was not what this number measured. Versus MC-only bury it was unresolved. Kitty-bonus tail risk is not removed. |
| 4 | **M1 value net** | the release-24 shortlist package (the standing capped control) | **+0.021 [+0.004, +0.039]** | ten 520-cluster windows on deals no other arm used | The one confirmed model gain of the shortlist era (MDE80 0.025). Width, depth and the last data doubling inside the shortlist bought nothing in play. |
| 5 | **Policy prior v2** (release 27) | hand-written prior | −0.0003 [−0.0017, +0.0012] | paired vs M1 | No resolved difference. Shipped to bound the wide tail above 1,000 legal actions, not for strength. |
| 6 | **JS-M1 as one package** (release 28) | M1 + separate prior | +0.006 [−0.016, +0.028] | paired vs release 27 | No resolved difference, and not an equivalence result. Shipped as cost and maintainability: one file is both prior and value net. |
| 7 | **Policy/value search, soft head** (release 29) | the release-28 package | **+0.086 [+0.042, +0.131]** card play; **+0.049 [+0.003, +0.095]** as served | 800 matched deals, one pre-registered primary; five clean 520-cluster windows | The head IS the search: its policy admits 8 of the legal actions over 64 sampled worlds, its value head prices them, no playouts. Versus MC-LCB in the ladder +0.187 [+0.144, +0.231]. The served read is a common-opponent summary-level estimate, not paired served-vs-served inference, and its lower bound is near zero. |
| 8 | **Hybrid-bury fix** (release 30) | release 29 | not measured | — | Correctness: the bury stopped refusing its own decision and silently falling back to the heuristic on ~6% of banker burys on the diagnostic capture set (24 of 400; the production-traffic rate is unmeasured). No strength claim. |
| 9 | **SMV3 outcome head** (release 36) | the release-30 package, same search | **+0.0393 [+0.0033, +0.0752]** as served (confirmation v36a2; the first read v36a +0.0361 [+0.0015, +0.0707]) | five 520-cluster windows each, common MC-LCB control, vs release 30 as served | The gen-5 SMV3 checkpoint 3e89e86f's OUTCOME head (arm F's recipe + sidecar v3, #658) in release 30's search unchanged. Confirmed by a predeclared second read; a common-opponent summary-level estimate like row 7. Policy head alone beats the production head +0.21 level/round in paired duels while served head swaps sit within ±0.02: measured decoupling, not a ceiling (#663). |
| 10 | **Search rules div + rc + tb + la** (release 38, deployed 2026-10-03) | release 36/37, same package | **+0.0461 [+0.0242, +0.0681]** (div + rc + tb vs release 36, ten fresh windows: CONFIRMED); +0.0106 [+0.0006, +0.0205] (+ la over that combination, ten windows: POSITIVE incremental) | 520-cluster windows, common MC-LCB control | One confirmed contrast (the three-rule combination, #676 issuecomment-5962364713) and one small positive incremental contrast with a lower bound near zero (lead-anchor on the combination, issuecomment-5965252288), which is not a second confirmation. Indirect reads through the common control, not head-to-head win rates, and not additive. Alone, div, rc and tb were unconfirmed or inconclusive; lead-anchor alone was positive exploratory (+0.0138 [+0.0013, +0.0262], five windows, below the extension triage). Deployed as release 38 on 2026-10-03 09:41 ET; play p50 ≈ +10% latency, zero fallbacks. |
| 11 | **Doomed-throw swap `dts`** (release 42, deployed 2026-10-06) | release 38, same package and rules | −0.0002 [−0.0102, +0.0099] as served (v57dts, ten fresh windows: INCONCLUSIVE; the first read v53dts −0.011 [−0.025, +0.002], five windows, inconclusive) | ten fresh 520-cluster windows, common MC-LCB control, vs release 38 as served | No strength claim. Shipped for correctness of play: on a lead whose throw the engine refuses in every sampled world with the same forced component, the bot plays that component instead of the doomed throw. The deploy gate read DEPLOY-ELIGIBLE, meaning not statistically demonstrated negative; it is NOT noninferiority, and harm stays compatible with the interval (about ±0.01). Mechanism, descriptive: failed bot throws 12,239 → 4,402 (−64%), 33.58 → 12.07 per 1000 plays, rounds with a failed throw 62.6% → 35.1% (#707 issuecomment-6026001554). Deployed as release 42 on 2026-10-06 19:08 ET. |

**Gen 5, not taken (2026-09-24 to 09-27).** Five one-variable retrains of the production head, each screened as
served vs release 30 on five fresh 520-cluster mirrored windows (common MC-LCB control, DL random effects, MDE80 ≈
0.05):

| arm | change | vs release 30 |
|---|---|---|
| A | MC-LCB corpora dropped | **−0.061 [−0.096, −0.025]**, resolved and negative |
| B | MC-LCB restored | +0.012 [−0.024, +0.048] |
| C | every corpus we own, 496k deals | −0.003 [−0.039, +0.032] |
| D | arm C warm-started from the best gen-4 head | −0.018 [−0.053, +0.016] |
| F | arm C with the #649 policy-target units fix | +0.010 [−0.025, +0.045] |

Corpus volume, composition, warm start and policy targets are not levers at this MDE. #649 found the 16 pv-search
corpora had taught the policy head a uniform target (half-level means under a points-calibrated temperature); #650
fixed the extract. The fix moved neither the holdouts nor the served read: the served search uses the policy head
only to admit candidates, and the value head decides.

The search-mean head has never been the production value function. It was served once, in a screen after these
five arms (v36b, 2026-09-29): the SMV3 checkpoint's search-mean head as the value function read
**−0.0523 [−0.0905, −0.0140]** against release 30 as served, resolved and negative, and was not shipped. Release
36's package comes from that same checkpoint, which was trained with the search-mean sidecar v3 (#658), but the
served search prices candidates with the outcome head only. The screen does not settle a search-mean head trained
on all candidates (#663 step 4). Full record: Atlas v2 and the scaling log.

**Exploitability, not established (#625, closed 2026-09-28 on Jerry's call).** A belief-reweighting attacker (the
search's own 64 worlds reweighted by an opponent model's likelihood of the observed plays) is HARMFUL, not weak. The
positive control against SmartBot read **−0.249 [−0.273, −0.225]** (ten of ten windows). Diagnostics on real deals:

- the opponent model is correct (99.8–100% of SmartBot's plays reproduced from the true hands);
- the loss is estimator variance (the posterior collapses to ~2 of 64 worlds);
- candidate margins (~0.02 half-levels) sit far below estimate noise (~0.5).

The earlier x36a null against MC-LCB is therefore not a bound on anything. A best response needs the opponent inside the
rollout continuation.

**Since release 36, not taken (2026-10-01 to 10-03).**

- PUCT tree search on the SMV3 package vs release 36 (P1 r4, five windows, exploratory): package prior
  **−0.417 [−0.463, −0.371]**, uniform prior **−0.894 [−0.928, −0.861]**. Closed (#436 issuecomment-5962752743).
- Root-allocation pilot A6 (learned-prior PUCT, uniform PUCT, successive halving vs uniform W64 on 24 DEV roots):
  closed (#436 issuecomment-5962069171).
- Adaptive K16 on multi-card leads: −0.0061 [−0.0303, +0.0181], inconclusive (issuecomment-5963808991).
- SMV3-SL4 (the runSL1..4 stores' trajectory, value and policy supervision added, recipe unchanged) served vs
  release 36: −0.0162 [−0.0600, +0.0275], inconclusive (v40a, #663).

**Not taken.** Each of these failed to clear zero against its own parent: more worlds beyond 64 (W128−W64 +0.024
[−0.034, +0.083], W256−W64 +0.024 [−0.033, +0.081]), K16, bounded PUCT, learned continuations, adaptive allocation,
and every warm-started generation as a shortlist package (v33 −0.007 [−0.038, +0.024]).

Receipts: rows 1–6 in the condensed shortlist-era section of
`docs_archive/ai-policies-release-sections-through-r38.md` and the linked run records; rows 7–10 in
`docs_archive/deploy-releases-28-38.md`, the scaling page and the search atlas.

## Callable policy families

If this summary and `server/shengji/ai/registry.py` ever differ, the registry is authoritative.

| family | intended use | current status |
|---|---|---|
| `heuristic` | Stateless legal baseline and stable Elo anchor. | Supported baseline, not production. |
| `smart`, `smart-v1`, `smart-v2` | Public-memory heuristics: card counting, boss/void inference, point flow, safe throws, ruff risk, bury and endgame rules. | Supported baselines and rollout policies. Exact lineage stays source-bound. |
| `mc`, `mc-lite`, `mc-strong`, `mc-vstrong` | Determinized Monte Carlo at named work levels. `mc` is the source fallback; `mc-strong` is N=30 and a historical rollback. Current rollback boundaries are in `DEPLOY.md`. | Supported. A legal sampler is not a calibrated belief model. |
| `mc-s0-*`, nulls, prefix policies | Frozen search/report experiments and matched controls. | Experiment/reproduction only unless `fly.toml` names one. |
| structured-bury, exact-endgame, point-banking, pair/throw and ballot variants | Mechanism-specific experimental constructors. Some intentionally remain outside the global registry to preserve evidence identity. | No production authority. |
| learned checkpoint policies (`rl`, V11, teacher, Direct-Q and successors) | Offline diagnostics, bounded proposals/rankers, or explicitly reviewed experiments. | Lazy/opt-in only. The one learned package production serves is the `pv-search` package named in the production contract above (last row). |
| `mc-cwv-<ckpt8>-w<W>`, `mc-cwv-prior-<ckpt8>-w<W>` | One-ply search whose ENTIRE evaluator is the complete-world value net (`ai/cwv_policy.py`): production's ballot and sampler, W sampled worlds, every (candidate, world) afterstate scored in one batch, argmax of the mean. The `prior` twin is the no-learning control (same positions, the training receipt's stratified prior as the value, in the prior's own utility scale -- PT0 integer levels for the training build's `baselines` prior, with exact terminals converted to match). Registered by `register_cwv_policies` or `SHENGJI_CWV_CKPT`; the checkpoint id is part of the name and a checkpoint whose encoder identity differs from `value_afterstate`'s is refused. | Dev screen only (`scripts/cwv_duel.py`, budget ladder 1x/3x/10x of production's wall). No strength claim; no production authority. |
| `mc-s0-report-lcb-x3`, `-x10` | Production with its selection and report doses scaled together (N=90/R=900, N=300/R=3000): production's own compute curve, the bar a learned arm must beat at each budget. | Reference arms for the ladder only. |
| `mc-shortlist-<ckpt8>-w<W>` (`CWVShortlistBot`; DEV) | Exhaustive legal actions ranked by the complete-world model over W sampled worlds; K4 or K8 alternatives plus incumbent go to full N30/R300 MC. Unlike `mc-cwv-*`, the model does not replace the final rollout evaluator. Registered by `register_cwv_shortlist_policies` or `SHENGJI_CWV_SHORTLIST_CKPT` so `make_bot` (and `harvest/trajectory.py --policy`) can reach it; the entry point REFUSES to hand back anything that is not a `CWVShortlistBot`, because `mc-cwv-<ckpt8>-w32` is the one-ply bot, not this one. | Historical: W32 PLAY and hybrid BURY were production from release 22 through release 28, with bounded heuristic fallback. Since release 29 this family is a registered rollback only (the release-28 name; its keys stay in `fly.toml`). The era is condensed in `docs_archive/ai-policies-release-sections-through-r38.md`. |
| `pv-search-<ckpt8>-w<W>-k<K>[-<rule tokens>]-r<recipe8>[-bury-hybrid-<id>]` (`PVSearchBot`, `PVSearchBuryBot`; `train/pv_search_policy.py`) | The one-ply policy/value search: the package's policy head admits K of the legal actions over W sampled worlds and its value head prices them, with no playouts; the hybrid bury runs on the same package. Registered by `register_pv_search_policies` when `SHENGJI_PV_CKPT` and `SHENGJI_PV_SHA256` are set; the name is derived from the environment. | PRODUCTION since release 29. Release 42 is W64/K8 with the rule tokens `div`, `rc`, `tb`, `la` (release 38) and `dts` (release 42) and hybrid bury (the production contract above). |

Example local selection:

```bash
SHENGJI_BOT=smart uv run shengji-server
```

In code, always pass a deterministic policy seed:

```python
from shengji.ai.registry import make_bot

bot = make_bot("mc-strong", seed=1234)
```

## Search and heuristic behavior that survives

Governing conclusions only; do not reproduce old toggle grids here.

- N=30 Monte Carlo clearly improved on the smaller base search; uniform N=60 did not establish another gain.
- The conservative disjoint R=300 report fold is the confirmed improvement; alternative confidence and
  adaptive-allocation recipes did not establish an additional winner.
- The heuristic incumbent must remain candidate zero. Tractor-lock, point-shy near-tie handling, deterministic
  ballot order and exact work counters are policy identity.
- Public memory may use declarations, plays, voids, remaining-pair/run bounds, the actor-private hand, and the
  banker-private burial where applicable. It may not read other hidden hands or a non-banker burial.
- Safe-shuai, boss/pair/tractor, point-flow, ruff-risk, void-building and endgame heuristics are useful parents and
  diagnostics, not proof that every fallback is strong. Before patching a production-policy quality gap, replay it
  and attribute it to legality, ballot, world sampling, continuation or value.

The old exhaustive toggle table is in Git history. Source owns what is enabled now; old head-to-head rates are
screening evidence, not production claims.

## Scaling and search insights (through 2026-09-22)

Every run and screen, with its receipt, is on the scaling page (`docs/scaling_log/`) and in the search atlas. Durable
conclusions:

**Models.** Offline cross-entropy does not order play: the programme's best CE played like the leader. The last
full data doubling inside the shortlist bought −0.0036 CE and nothing in play; width and depth alone did not move
play. Encoder v2 was the one real gain; v3–v5 bought nothing. Warm-started generations were null as packages. Through
2026-09-22 the policy head alone was SmartBot-level under public information (soft head +0.052 [+0.039, +0.067];
JS-M1's head −0.0137 [−0.0269, −0.0004]). The gen-5 heads are stronger alone: SMV3's head beats the release-30 head by
+0.21 in a paired head-only duel (ladder row 9). That duel uses the head-alone harness that sees the true hands, so
it is not a public-information read, and the gain did not carry into the served search. The soft target (the
search's own values as the policy target) is the ingredient with the largest point estimate in the head-driven search; no head in the W64 family is
shown superior to another. Corpus seeds are decks and are excluded from screens per model.

**Search.** Worlds were the lever through 64; the ladder shows no resolved gain beyond (numbers under "Not taken";
unresolved, not equivalence). K8, not K16. The value head replaces playouts outright (ladder row 7). A T1 value
cutoff beats terminal-level MC; learned continuations and bounded PUCT lose or add nothing at large cost multiples.
The served read (+0.049, a common-opponent summary-level estimate, not paired served-vs-served inference) is smaller
than the card-play read (+0.086, different deals and design), with no measured cause. The deploy gate is the served
design.

## Current scientific conclusions

| lane | conclusion for policy work |
|---|---|
| **RLCB** | The confirmed MC-LCB search; the historical screen baseline through 2026-09-21. Superseded in production by the model-guided shortlist (W32, then M1 + prior, then the JS-M1 joint model), and from release 29 by the head-driven policy/value search, which uses no MC playouts in play. |
| **Search rules on the head-driven search (release 38, deployed 2026-10-03; `dts` added in release 42, 2026-10-06)** | Admission diversity, refusal-constraint sampling and the points tie-break CONFIRMED only in combination (+0.0461 [+0.0242, +0.0681] vs release 36, ten fresh windows); lead-anchor on that combination read +0.0106 [+0.0006, +0.0205], POSITIVE incremental with a lower bound near zero, not a second confirmation; lead-anchor alone was positive exploratory, below the extension triage. Adaptive K16 inconclusive; PUCT and root allocation closed. The doomed-throw swap `dts` (release 42) read −0.0002 [−0.0102, +0.0099] vs release 38, ten fresh windows: INCONCLUSIVE, deploy-eligible (not noninferiority), shipped for correctness with failed throws −64% (descriptive). All are indirect contrasts through the common MC-LCB control. |
| **Head-driven policy/value search (release 29, 2026-09)** | The soft head as the whole search beats MC-LCB at W16, W32 and W64 in the ladder (W4 loses), the release-28 package in card play (+0.086 [+0.042, +0.131]) and release 28 as served (+0.049 [+0.003, +0.095], narrow; a common-opponent summary-level read, not paired inference). No resolved gain beyond 64 worlds in the ladder; no head in the W64 family shown superior; at release 29 the next production claim needed a served contrast against release 29; the comparator is release 38 as served (release 42 proposed, pending Jerry). |
| **M1 / policy prior v2 / JS-M1 (2026-09)** | M1 confirmed on fresh deals (+0.0212 [+0.0036, +0.0387]); the prior's paired contrast with M1 is −0.0003 [−0.0017, +0.0012] (no resolved difference) with 0 decisions >60 s in the 365k observed; JS-M1 as one net reads +0.0057 [−0.0163, +0.0277] paired vs the two-model arm (no resolved difference, not established non-inferiority) and +0.0239 [+0.0005, +0.0472] vs release 24 at five (nominal). Deployed as release 28. The owed fresh-seed read came back inconclusive with a negative point (−0.0159 [−0.0383, +0.0065] paired vs release 27, five fresh windows, 2026-09-17), so release 28 carries no strength claim; no ten-window read is recorded. |
| **Global learned rankers / V11 / Direct-Q / teacher direct play** | Better label fit or isolated proposal signal did not transport into a stronger whole-game policy. Keep learned scores bounded to their reviewed role. |
| **S4 point banking, S6 shuai sourcing, pair-aware continuations** | Mechanisms were plausible or locally positive but no registered whole-game successor cleared the required bar. Do not revive them as unchanged retries; reopen only with a materially different axis, not a larger retry. |
| **T4 model proposal** | Selected none. The uninformed widening control was positive against champion but used 14.8% more accepted worlds and 80.9% more searches; it requires a three-arm compute/candidate attribution test before claiming that widening itself won. The later W32 shortlist screen does not settle that experiment. |
| **BELIEF R4/R5** | R4's preserved synthetic-primary cohort reduced held-out count Brier by 21.40% versus REF-C, but the permuted-label control also improved materially and failed on demand — a predictive channel, not behavioral belief learning. The opened-DEV consumer diagnostic then sealed `NO_PRIMARY_POLICY_SIGNAL` (ESS 97–99.5% of maximum, 1/104 flips, paired value exactly zero). R4 is terminal; no R5 compute proceeds unless a separate oracle-belief probe shows a gain worth reopening. No BELIEF sampler, candidate, or policy is registered or deployable. |
| **BELIEF V1/R3 resource failures** | They provide no learning verdict. They motivated reusable artifacts, measured scheduling, graceful truncation, progress telemetry and the R4/R5 recovery path. |
| **PT0** | Privileged late-endgame policy had a small edge over heuristic/smart and an inconclusive edge over production MC. |
| **PT1** | Clean negative for the frozen scope despite high action-flip dose: the exact teacher changed many actions but produced only `1/208` mean C−B and one positive state, missing all efficacy gates. The retired backlog recorded that the recovered result carries a preregistration-governance caveat and is not a clean general closure of late-game teacher search. |
| **PT-Full** | A single true-world collapse was bad; repeated true-world search recovered most of that loss but did not beat the public ensemble. Preserve posterior ensembles. |
| **C0** | Fixed perfect-information consumer variants all lost to both required parents; local bare-point symptom fixes did not transport. |
| **K8 shortlist** | Exploratory DEV screen: +0.08203 versus production (95% CI `[+0.00972,+0.15430]`), but −0.05664 directly versus K4 (95% CI `[-0.11328,-0.00391]`; 17 favorable / 32 unfavorable / 207 tied). Keep K4; no K16 escalation or deployment. |
| **Value-Afterstate V0** | `REFUSE_MECHANICS_OR_NEGATIVE_CONTROL` (2026-08-28, source `d9ad99f6`, independently verified): the first afterstate value screen refused on its own mechanics/negative-control gates; no value signal was established. |
| **Value-Afterstate V1 P1** | `SELECT_NONE_NO_ACTION_ADVANTAGE` (2026-08-29, reproduced exactly): the natural arm was the worst of four, beaten by two of its own negative controls. A clean learning null that motivated the V2 absolute-leaf redesign. |
| **PT-Sol0 / PT-Luna0** | First reviewed flexible-planner milestone. On the same 26 full-round roots and 52 mirrored treatment roles, Sol beat exact production arm A by `+17/26` signed levels per role and Luna by `+5/13`; both also beat B and C0-S on average. Luna was `-7/26` versus Sol, so Sol remains the quality teacher while Luna is the cheaper scaling candidate. This is open-DEV privileged-information mechanism evidence—not a registered policy, fresh strength result, or deployment authority. |
| **PT-Luna isolated (b0b1bd95)** | First COMPLETE terminal of the teacher lane (ledger `6c71bee3`): 32/32 games, 16/16 clusters, 0 failed, 21,979,625 tokens, independently reconstructed. Readable only for the scoped teacher/value research; label ingestion and training are separate gates. Four predecessor routes (30 games, 24,749,862 tokens) are engineering-only. Its planned use is diagnostic (where the flexible planner beats production, by mechanism) and as a fine-tuning/evaluation value target — not action imitation. |
| **PT-Luna batch4 versus compact1 (completed #280)** | 52 deals / 104 mirrored rounds: batch4−compact1 −0.1058 levels/round [−0.2885,+0.0769], with 2.27× fewer reported tokens/decision and 1.70× serial provider throughput. Equal quality is not established; seven shared-response waves limit the deal-bootstrap interval. Neither play-only arm is the historical rollout-enabled teacher or production MC. Retained native exports: 3,900 fit + 3,852 validation records, disjoint deals and losses preserved. Opened validation is not fitting data or fresh confirmation. [Readout](server/runs/luna_quality_gameplay_tranche1_result_20260906.md). |
| **Value V2 D64 (2026-09)** | Sealed `D64_DEV_SEALED` at exact source `11c43839` after 12 training epochs. On 12 natural audit deals, outcome-distribution RPS improved by `+0.006400834` (90% deal-bootstrap interval `[+0.002789151,+0.010361512]`; 4/4 members positive), but expected-value absolute error worsened by `-0.178319` signed levels (`[-0.306394,-0.037274]`) and paired action-sensitivity error worsened by `-0.045395` (`[-0.058033,-0.032902]`). Selected-action utility was inconclusive at `+0.0625` (`[-0.21875,+0.375]`) with 91.7% action-change dose and worst-decile utility `-0.8125`. This is small-DEV evidence of distribution-shape learning without calibrated scalar/action value, not a usable consumer or strength result. The frozen 256-slot ledger and 255 realized shards are coverage-audit evidence only; no missing-slot completion or slot-targeted D256 training follows. |

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
hypotheses. Strength requires a fresh mirrored whole-game comparison against the exact live champion, followed by
confirmation when the design calls for it.

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
- Production does not enable experimental posterior-changing sampler flags.
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
| active fleet, open investigations and exact review asks | `server/scripts/fleet_status.sh`, the board issue #707 (its predecessor #679 is closed and holds everything finished through 2026-10-03) and its topic issues (#663 model, #676 search screens, #436 PUCT/allocation, #355 Sol benchmark, #681 mistake audit), and the owning GitHub issue or PR (`HANDOFF_ACTIVE.md` was deleted, #674) |
| callable code | `server/shengji/ai/registry.py` |
| production config | `fly.toml` |
| model/belief/teacher design; research architecture and model lineage | `RL_PLAN.md` |
| immutable evidence and review corrections | `HANDOFF_REVIEW.md` authority markers (frozen to its markers, #674; verdicts and reviewer corrections are PR review comments; prose lives on GitHub issues; archived text in `docs_archive/handoff-review-*.md`) |
| engine/sampler contract | `server/tests/`, `incidents/` (ledger archived at `docs_archive/correctness-through-2026-09-22.md`) |
| performance and deployment | `DEPLOY.md`, issue #208 (the speed record is archived at `docs_archive/perf-through-2026-09-22.md`) |
| what each production change bought | the ladder table above |
| screen results since release 29 | `docs/atlas_v2/registry.json` (Atlas v2) |
| agent execution discipline | `AGENTS.md` (the daily routine is archived at `docs_archive/maintenance-through-2026-09-22.md`) |
| old policy/toggle ledger | Git history and `docs_archive/` |
