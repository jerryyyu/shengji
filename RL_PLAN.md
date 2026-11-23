# Learning and search research plan

As of 2026-11-22. Production is release 55 (the RT4 unified model, bury at 3 s); new duels and screens compare
against release 55 as served (deployed 2026-11-22), read against the two-stage duel bar (2026-11-03).

This file owns the research architecture, the estimands, the process rules for compute and measurement, and the
lessons that shape planned work. Everything else lives on its canonical surface:

| what | where |
|---|---|
| open questions, row state, next tests and bars | board issue [#1263](https://github.com/jerryyyu/shengji/issues/1263) (predecessors #1075, #707, #679, closed) |
| model plans and decision gates; search diagnostics | #663; #700 |
| production contract, measured ladder, policy names | `AI_POLICIES.md` ("Production contract", the ladder table) |
| releases, rollback, deploy checklist | `DEPLOY.md` |
| every screen | Atlas v2, `docs/atlas_v2/registry.json` |
| training runs | Atlas v2's models table (`registry.json` `models`); the scaling page, `docs/scaling_log/`, through 2026-10-02 |
| fleet state | `server/scripts/fleet_status.sh` |
| this plan's history and full detail | `docs_archive/rl-plan-through-2026-10-16.md` and earlier `docs_archive/rl-plan-*` files |

## Glossary

| term | meaning |
|---|---|
| **level/round** | the primary metric: paired signed level utility per round, clustered by deal seed |
| **window** | one 520-cluster mirrored screen block of fresh deal seeds |
| **MDE80** | minimum detectable effect at 80% power for that readout |
| **as served** | the full production bot path, including declare, bury and budgets |
| **comparator** | the champion a new strength claim must beat; now release 55 as served |
| **MC-LCB** | the confirmed Monte Carlo search; the common control inside each ten-window screen (through 2026-10-25), not the comparator |
| **duel** | the default screen since 2026-10-25: the candidate plays the served release head to head on the same deals, seats swapped |
| **SCREEN_PASS / CONFIRMED** | the two duel-bar verdicts (3,920-deal screen; 7,840-deal fresh-seed confirmation); "Duel bar" below |
| **W / K** | sampled worlds per decision / candidates the policy head admits (served: W64, K8) |
| **head-driven search** | policy head admits K candidates, value head prices them over W worlds, no playouts |
| **rule tokens** | served search flags (`div`, `rc`, `tb`, `la`, `dtr`, `vd`, `bwv`, `vdef`, …); defined in `AI_POLICIES.md` |
| **D7 + X7** | exact endgame stages at ≤ 7 cards: lead (D7) and follow (X7) |
| **belief worlds** | play worlds whose hidden hands the belief model proposes: the unified model's belief head (RT4's `ut-rt4-belief-35e225cf` since release 55, the all-data model's `ut-all-belief-1b1fd2de` in releases 53–54); B1a (`028131a0`) in releases 50–52, S58 in 48–49, S17 in 46 |
| **unified model** | one transformer whose trunk forward per decision feeds the belief, the root prior and a per-leaf readout (value and reply ranking); served in four slots of the play search since release 53 (`ushare`, `uvalue`, `ureply`; fast path `ufast`); the all-data model `97c07be8` in releases 53–54, RT4 `e2951d35` since release 55 |
| **first-round / later-round** | deals where the declaration decides the banker / where the banker is fixed |
| **val_ce** | offline validation cross-entropy, a checkpoint-selection signal |

## Objective and evidence standard

Build a Shengji policy demonstrably stronger than production, under a correct engine and a reproducible evaluator:
beat the served bot on fresh mirrored whole games with one learned model that keeps improving from its own search
data, with production's latency tail bounded. The standing goal is +0.05 levels/round over the served release
(Jerry 2026-10-15; board #1075).

- **Production:** release 55, deployed 2026-11-22 {{DEPLOY_ET}} EST (Fly {{FLY_VERSION}}; Jerry, in session 2026-11-22,
  "Yup let's ship the better model"): release 54 with the RT4 unified model (the 500k-round point of S150, warm from
  the all-data model) in its four unified slots, every other line release 54's. The fresh-seed confirmation S159
  measured +0.0612 [+0.0510, +0.0712] against release 54 as served (CONFIRMED, 7,840 paired deals, one-sided 95% lower
  bound +0.0527) on the M5 Ultra (`AI_POLICIES.md` row 24); no screen against release 54 ran (the DEV duels R4H and
  R4F read against release 53's unified model and FT-200k). Fly timing 0.993× release 54 (CI 0.977–1.010), one game
  at a time. Its strength on Fly and with human partners is not measured. Release 54 (release 53 with the bury budget
  at 3 s, row 23; deployed 2026-11-19 18:14 EST, Fly v118) is the rollback; release 53 (row 22) put the all-data unified
  model into release 52's search, +0.0521 [+0.0410, +0.0633] vs release 52. Exact contract: `AI_POLICIES.md`
  "Production contract".
- **Comparator:** new duels and screens compare against release 55 as served (from its deploy, 2026-11-22).
  Confirmations keep their parent's comparator; historical reads keep their original labels. The previous comparators
  were release 54 (2026-11-19; release 53 differed from it only in the bury budget), release 52 (2026-11-09), release
  51 (2026-11-06, with the lcc-off release; lcc off on both sides), release 50 (Jerry, in session 2026-11-04, "Yes
  move comparator"), release 49 (Jerry, in session 2026-11-01), release 48 (Jerry 2026-10-24, in session: "Yes
  screens should compare vs our prod policy of r48"), release 46 (Jerry 2026-10-16, recorded on #1075) and release
  45 (Jerry 2026-10-13, #988 issuecomment-6142666693).

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

- **Cheap DEV test before a screen.** An offline metric (agreement, calibration, true-world regret, coverage) does
  not by itself admit a screen. A new lever first passes a cheap DEV test with a bar written before it runs (an
  offline bar, or a small paired seat-swapped duel against the served release); only then does it get a screen
  duel under the "Duel bar" below. A 600-deal duel resolves about ±0.075 levels/round, so when the expected gain is
  smaller its bar is no regression and no operational fault (fallbacks, expiries, latency), not a positive
  estimate. Offline gains have not carried: belief epoch 8's +0.83 pp agreement read +0.0062 [−0.0118, +0.0243] levels/round (v95s17e8);
  wide lead admission's 45.5% outside-K8 gap read +0.0168 [−0.0078, +0.0414] (v94wla46).
- **Strength ceiling before cost work.** A search mechanism's first gameplay test runs with its serving deadline and
  node caps lifted. Latency or approximation work starts only after a positive ceiling; a null ceiling parks the
  mechanism.
- **Combination candidate.** The largest served gain came from composing proven parts: release 46 read
  +0.2284 [+0.2046, +0.2521] vs release 45, more than its parts' sum. Keep one running combination of near-miss
  levers on the board and test it as one duel rather than each lever alone.

**Duel bar: screen, then confirmation (Jerry 2026-11-03)**

A paired seat-swapped duel against the served release reads levels/round with a deal bootstrap (10,000 reps,
seed 1). Two stages replace the single DEV bar (mean ≥ +0.015 and 95% CI lower > 0 on 3,920 deals):

1. **Screen (DEV):** 3,920 seat-swapped deals. SCREEN_PASS iff mean ≥ +0.005 and the one-sided 80% lower bound
   (the 20th percentile of the bootstrap means) is > 0; otherwise SCREEN_FAIL. Validity guards run first and an
   invalid arm is DEV_INVALID. A screen PASS earns a confirmation or a place in a combination, not a release.
   Readers also print the 95% interval and the single-bar verdict as a descriptive `old_bar:` line, so reads stay
   comparable with earlier duels.
2. **Confirmation:** fresh seeds, 7,840 deals. CONFIRMED iff mean ≥ +0.005 and the 95% lower bound (2.5th
   percentile) is > 0.
3. **Release:** unchanged: a confirmed duel, Fly timing and Jerry's word (`DEPLOY.md`).

Pass probability by true effect (per-deal sd ≈ 0.485, g3dsc; normal approximation):

| true effect (levels/round) | 0 | +0.005 | +0.010 | +0.015 | +0.020 |
|---|---|---|---|---|---|
| single DEV bar, 3,920 deals | 2.5% | 9% | 25% | 49% | 73% |
| screen, 3,920 deals | 20% | 42% | 67% | 86% | 96% |
| confirmation, 7,840 deals | 2.5% | 15% | 45% | 78% | 95% |
| screen then confirmation | 0.5% | 6% | 30% | 68% | 92% |

The two-stage rule applies only to runs not yet started when it was adopted (2026-11-03 ~15:45Z). Every run started before then, on any date, keeps the bar it predeclared; its readout is read and labelled against that bar.

## Planned work

**What changes production next:** a change that passes the duel bar against release 55 as served (a screen, then a
fresh-seed confirmation), then the `DEPLOY.md` release checklist and Jerry's word. Release 55 shipped on a fresh-seed
confirmation against release 54 (S159) after two DEV duels against other comparators (R4H, R4F), offline gates, a
pre-deploy smoke and a single-game Fly timing; release 53 shipped on a screen
(UT-alldata-screen) and a fresh-seed confirmation (UT-alldata-confirm) against release 52, launch checks (UT-launch) and
a single-game Fly timing of the fast path (UT-fly-fast); release 52 on a screen (combo51) and a confirmation (combo51C)
against release 51 plus a single-game Fly timing run; release 50 on a confirmation against release 49 (cbaC) plus a
duel screen (cbaf) and the R50 speed profile. Configuration changes may ship with no strength claim (release 54's
bury budget), as may correctness fixes when the served screen is not demonstrated negative (releases 42, 43).

**Direction (Jerry 2026-10-11, 2026-10-13):** "Where we use heuristics, it may be better to use the model";
after release 45, "we should keep trying in this direction." Heuristics still in the served bot: the play
anchor, the heuristic first trick inside each value leaf, and the continuations before the exact endgame.

**The unified model is the trunk of the plan.** Since release 53 one transformer serves the play search's belief,
root prior, leaf values and replies, so the next gains are expected from more and better data for that one model
and from targeted heads on it, each measured against release 54 or against the confirmed all-data model where the row
says so. Rows as of 2026-11-20 (board #1263 is authoritative for state, next test, bar, owner and host; parked rows
and their failed bars are on the board):

| row | what | measured so far | next test and bar |
|---|---|---|---|
| S139 | RT2: warm-start retrain of the all-data model on a bigger quality-weighted mix (+2.6M unified self-play rows at ×2 policy and reply weight, X3R 1.5M, PVS R46 12.2M at ×0.5) | DEV vs the all-data model +0.0285 [−0.0005, +0.0575], LB80 +0.016 (bar ≥ +0.02, LB80 > 0, PASS); vs release 52 +0.0735 [+0.0435, +0.1035]; offline gates PASS. The 3,920-deal screen vs the frozen release-53 winner recipe (the all-data model 97c07be8), both arms on the plain readout, was read on 2026-11-20 as SCREEN_PASS +0.0191 [+0.0043, +0.0336], LB80 +0.0128 ([#1263 issuecomment-7027806400](https://github.com/jerryyyu/shengji/issues/1263#issuecomment-7027806400)); it does not establish that the gain transfers to the fast serving path or to release 54; its archive and Atlas row are pending | the 7,840-deal fresh-seed confirmation (mean ≥ +0.005, one-sided 95% lower bound > 0); then a release candidate against release 54 |
| S150 | UT-GEN2: unified self-play to 500,000 rounds on the M5 Ultra (Jerry 2026-11-19); iterated self-play: tranche A (100k rounds) by release 53 as served, then tranche B, from leg B01 (the first r2-chain leg, after tranche A finishes), by RT2 once RT2's screen ends PASS; each leg records its generator | 500k rounds generated (2026-11-21); generators by segment: release 53, RT2, then RT3-FT after its 2026-11-20 screen PASS. RT4, the 500k point (warm from the all-data model, one pass over RT2's mix plus every UT-GEN2 row of the 500k cut): R4H vs release 53's unified model, plain readout, +0.0689 [+0.0546, +0.0834] (3,920 deals); R4F vs FT-200k +0.0355 [+0.008, +0.064]; confirmed vs release 54 as served +0.0612 [+0.0510, +0.0712] (S159) and served as release 55 (2026-11-22) | the 1M continuation by PLAN_1M's continue rule read at RT4 (continue unless the curve is flat), with the best confirmed bot, now release 55, as the generator; RT5 at 1M, then the M and L size arms (S156); offline points on fixed holdouts plus a duel per point |
| S146 | banker-void belief gap: the banker is void in an unrevealed side suit 29.0% of the time where the belief implies 19.9%; when truly void, no sampled world has it 12.9% of the time | ceiling with oracle banker voids +0.0335 [+0.0075, +0.0600] vs the all-data model, 1,000 deals, LB80 +0.0225 (bar mean ≥ +0.02, LB80 > 0, PASS) | build a banker-void head (one output per side suit) with void-first world sampling; offline bar void ECE ≤ 0.02, no-world ≤ 3%, belief log-likelihood within +0.002; then a 1,000-deal duel (mean ≥ +0.015, LB80 > 0) |
| S147 | leads lose most to missing information: sampled-world best equals true-world best on 46.5% of leads (62.4% overall); true-world regret 0.079 levels per lead vs 0.014 per follow | audit only | blend the information-set Q head with the world mean on 2,362 cached leads; bar agreement ≥ 49.5% and regret ≤ 0.070, then a leads-only 1,000-deal duel |
| S148 | idle history attention: 12 of 36 heads ablate for under 0.005 nats; all token-to-token attention is worth 0.015 nats of belief | audit only | a one-encoder-layer arm warm from the all-data model; bar belief log-likelihood within +0.003, leaf NLL within +0.005, trunk ≥ 30% faster (a latency lever, not strength) |
| S149 | the reply ranking is weak on multi-card tricks: recall@4 single 0.949, pair 0.833, tractor 0.756, throw 0.698 | audit only | a whole-action reply scorer on frozen card states; bar +5 points recall@4 on pair, tractor and throw replies with singles ≥ 0.945, then a duel |
| S152 | the offline gate replays positions without refused-throw notices (35% of L25 rows carry one; the policy's top card flips on 4.5%) | audit only; the repaired gate consumer is in review (#1610) | re-run RT2's gate with the extract's own replay; if the deltas move < 0.005, note and close, else fix the gate |
| S151 | serving speed: the transformer is about 3% of decision time; the gains are in the Python around it | #1607 merged and served in release 54 (Mac all-play CPU ratios 0.998 and 0.997, decision-identical); #1609 (compiled feature-row builder), #1597 (forced-reply elision) and the compiled reply-child builder (#1608) passed source review and wait on rebase or CI | all decision-identical; the bar is one combined Fly timing after merge. Component percentages are not added into a claimed combined gain |

A packet built against an older release is rebuilt against release 55 before it is queued.

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
| Retrains from SMV3 to C16 did not beat production; the expert-anchored prior and the full-data value did | gen-5 arms, C11 e9 vs release 38 (v55e9r38 −0.0145), C12, C14 E5 (v84 −0.0133), C15, C16 Stage 1: inconclusive or failed; FT1 prior m30yc +0.0162 [+0.0024, +0.0306] and G3 Stage A value + FT1 g3dsc +0.0349 [+0.0203, +0.0492], both fresh-seed confirmations vs release 49 as served | corrected: the C15/C16 PV fine-tune line is parked (M13); FT1 + A are the base of the R50 candidate |
| Corpus seeds are decks | a window inside a corpus's seed range replays decks the model saw; ranges on #436, excluded per model | still true |

¹ The shortlist instrument tied 54–62% of deals and could not resolve head differences (warm-started generations
null as packages); the served W64 screens can. The M1 two-head recipe was the one shortlist-era confirmed model
gain, +0.021 [+0.004, +0.039].

### Model lineage

Each served model is a warm-started descendant of the one before. Sources are the Atlas v2 `models` and `screens` rows;
numbers are levels/round against the release named, as served. DEV duels are tier i (1,000 or 3,920 deals) and do not
replace the two-stage screen.

**Value and policy (the PV packages).** Until release 48 one package carried the trunk, the outcome (value) head and
the policy head. From release 50 the value package and a separate card-play prior package are served side by side.

| model | sha | warm start → recipe | read | served |
|---|---|---|---|---|
| soft head | 8ecd4fea | gen-3-warm recipe with the search's per-candidate values as soft policy targets, 256k deals | production head | release 29 |
| gen-4 runs 1–4 | 3f83bfb7 … 23ad5c3f | one-variable tests on 336k deals: hard vs soft targets, grid trunk, depth 6 | all cross zero vs release 30 (v34r1–r5) | no |
| gen-5 arms A–F | 9f4c9658 … e2645ec2 | 8ecd4fea retrained with corpus, warm-start and target changes (256k–496k deals) | A worse (−0.061); C, D, F cross zero | no |
| SMV3 | 3e89e86f | arm F + search-mean head trained on sidecar v3 (496k deals, 55M policy rows) | head vs release 30 v36a2 +0.039, confirmed | releases 36–49, as `smv3out-491ee4bf` |
| SMV3 variants, C11–C16 | b0bdf33d, 218bcf5c, 3a4e3d70, 801772f3 … | head weight, batch fraction, rollout labels, encoder v7 / 880k deals | inconclusive or failed; the PV fine-tune line parked (M13) | no |
| FT1 prior | 1fa201b2 | policy net fine-tuned toward ~37.8k expert-search labels (M30 P0) | m30yc +0.016 [+0.002, +0.031] vs release 49, confirmed | releases 50–52, as the separate prior; bound for unread replies and fallbacks since 53 |
| G3 Stage A value | f4f4127e | SMV3's served trunk retrained on all Y self-play (200k rounds), EMA epoch 4 | with FT1: g3dsc +0.035 [+0.020, +0.049] vs release 49, confirmed | releases 50–52 in play; declaration, bury and terminal leaves since 53 |
| G4 value | bd616b38 | G3 A + the 80k-round release-50 corpus | offline A1 failed; g4s +0.005 [−0.009, +0.019] vs release 51 | no |
| X2 prior arms PA, PF, PS | 54c3f2f4, 9a3d3395, 574f2409 | warm from G3 A, rebuilt FT1, SMV3; Y + R50 + 30k x1a self-play rows (x1a ×3), soft targets | X2H top-1 vs x1a +0.044–0.047 over FT1; DEV vs release 51: PA −0.042 [−0.072, −0.010], PF −0.006 [−0.038, +0.026], PS −0.040 [−0.070, −0.010] | no |
| all-data unified model | 97c07be8 (belief 1b1fd2de) | one 4.9M-parameter transformer (trunk width 192, 4 + 4 layers, a 3-block per-leaf readout) for belief, root prior, reply ranking and leaf value: one joint pass over 22.1M rows (Y 10.3M, x1a teacher X4 5.6M, R50 4.5M, x1a teacher X2 1.7M), warm from round 1, then a true-world head polish (epoch 8) | in release 52's search: UT-alldata-screen +0.057 [+0.042, +0.073], UT-alldata-confirm +0.052 [+0.041, +0.063] vs release 52, confirmed; belief calibration log-loss 0.9985 vs B1a 0.9878 | releases 53–54, in four play slots |
| RT2 | 47175c99 (belief bed32f87) | the all-data model warm-started on a bigger quality-weighted mix (S139) | DEV vs the all-data model +0.029 [−0.001, +0.058], pass; screen read 2026-11-20 vs the frozen release-53 winner recipe, both arms on the plain readout, +0.019 [+0.004, +0.034] SCREEN_PASS (archive pending); transfer to the fast path and release 54 not measured | not yet; confirmation next |
| RT4 | e2951d35 (belief 35e225cf) | the 500k-round point of S150: warm from the all-data model, one joint pass over RT2's 39.76M-row mix plus every UT-GEN2 row of the 500k-round cut (MPS to buffer 2365, finished on CPU), then the head polish (epoch 8) | R4H vs release 53's unified model, plain readout, +0.069 [+0.055, +0.083] (3,920 deals); R4F vs FT-200k +0.036 [+0.008, +0.064]; S159 vs release 54 as served +0.061 [+0.051, +0.071], confirmed; offline gates value −0.032, reply +0.021, PASS | release 55 |
| X2 value V | ff4199f7 | G3 A + G4 mix + x1a outcomes (×3) | DEV vs release 51 −0.017 [−0.045, +0.012]; with PA −0.026 [−0.057, +0.006] | no |

**Belief (hidden-hand model).** Served beside the PV packages since release 46; it draws the search's worlds (`bw`)
and, from release 50, the bury search's worlds (`bbw`).

| model | sha | warm start → recipe | read | served |
|---|---|---|---|---|
| S17 | — | first history-input belief net | soft-oracle probe v83sorc45 +0.309 (diagnostic); its e8 package v95s17e8 +0.006, inconclusive | its worlds (v86bw45 +0.117 [+0.091, +0.142] vs release 45) shipped in release 46 |
| S43, S46 r3 | — | rank-mixed corpora; S46 wider (d192) | screens positive: s43t +0.022 (T 1.35), s46screen +0.024; the S46 confirmation s46c +0.021 inconclusive | release-47 candidate, held; release 48 used S58 |
| S58 | 42444515 | S46 r3 continued 6 epochs, rank-mixed | calib log-loss −0.0135 nats vs S46 r3; with dtrx v103s58 +0.033 [+0.015, +0.052] | releases 48–49 |
| B1a | 028131a0 | S58 fine-tuned on the four Y stores (10.3M rows), 2 epochs, T 1.019 | test log-loss 2.24 pp lower than S58 (relative to the uniform baseline); cbaf B1a over S58 +0.023 [+0.001, +0.045] | releases 50–52 |
| X2B | 621dc9e2 | B1a fine-tuned on 30k x1a self-play rounds (1.7M rows), 2 epochs | X2H log-loss vs B1a 1.0021 → 0.9895⁴; DEV vs release 51 +0.024 [−0.006, +0.053], LB80 +0.011, DEV pass | not yet; two-stage screen next |
| X2BY | 85ec5fc3 | B1a on 50% X2 + 50% Y rows | X2H 0.9918; Y holdout 0.989 vs B1a 0.986⁴ | not duelled |

Lineage lessons, as read so far:
- The confirmed PV gains came from new data and new label sources (Y self-play for value, expert-search labels for the
  prior), not from architecture or capacity changes alone.
- The all-data unified model (release 53) changed the architecture and the data together: one transformer trained on
  all 22.1M rows confirmed +0.052 [+0.041, +0.063] vs release 52. Its size sweep (S140, 1,000 deals each vs release
  52, from scratch) read the medium size +0.038 [+0.0095, +0.0675], small and large near zero, and that medium model
  read −0.037 [−0.066, −0.010] against the warm-started, smaller winner: at 22M rows the warm start beat size.
- Distilling a stronger teacher's choices into the prior raised agreement with that teacher but did not raise served
  play; the x1a-distilled priors were even (warm from the served prior) or worse (warm from G3 A or SMV3) vs release 51.
- Earlier served belief updates (S58, B1a) improved play in confirmed screens; some belief variants (S17 e8, S46 at T 1.30)
  did not. X2B has a +0.0235 DEV pass that still awaits its formal screen and confirmation.

⁴ Recalibrated offline NLL comparisons: each model's temperature is refit on X2 calib (B1a T 1.102, X2B T 1.034, X2BY
T 1.031), not B1a's served T 1.019.

### Search

| lesson | evidence | status |
|---|---|---|
| Model proposes, search decides | W32 shortlist +0.139 on 256 rank-2 deals; K4 beat K8 | still true |
| The heads can be the whole search | head-driven search vs MC-LCB +0.095 at W16, +0.187 at W64; W4 loses | still true |
| No resolved benefit from the tested additional-world recipes; a better world draw helped | belief worlds v86bw45 +0.1165 [+0.0914, +0.1416]; 512 vs 64 worlds −0.0007 [−0.0022, +0.0008] per decision on 2,133 replayed decisions (board #707 S2 closure) | replaces "worlds are the lever" |
| A better policy head alone does not show in served play | head alone +0.24 vs SmartBot (arm F, 2026-09-30); value head decides | still true |
| The tested admission-rule combo beat its parent; the tested PUCT recipe lost | div + rc + tb confirmed together (release 38); PUCT −0.417 vs release 36 | tested recipes only; S35 (hybrid) and S38 (horizon) parked on their bars; deeper lookahead stays open (M31) |
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

1. **Admission and cost.** Release 49's search as served is the reference. Separate exact speedups from policy changes;
   compute-match controls when a claim is about cost.
2. **Depth and allocation.** Test one bounded change against the comparator before any larger tree recipe; the
   ballot-rooted PUCT ladder is closed.
3. **Model and teacher transport.** Improve data and targets against the actual consumer (the search's own values
   as the target), preserve held-out deals, then test the head in the same search on fresh seeds. A better teacher
   or better offline prediction does not guarantee this link.
4. **Paired worlds, and the flat W64 search as the yardstick** (search audit, 2026-10-15, S33). Every search
   variant scores all candidates, and every reply inside a lookahead, on the SAME sampled worlds. Never allocate
   one world per visit (PUCT v1's −0.417). Before any screen, a search change must beat the flat W64 K8 paired
   search offline on the audit's true-deal yardstick (the S33 audit probe and analyzer, not in the repository; their
   location is on #700 issuecomment-6219217579; same probe states): sf Δ ≥ +0.003 per decision with a 95% CI above
   zero, and vt Δ ≥ 0, on at least 700 decisions.⁴

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

1. While a predecessor runs, keep its next named successor on the board (#1263) or the owning issue: priority,
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
- A 1,000-deal DEV duel selects what gets screened; it does not establish a gain. X2B's DEV pass (+0.0235,
  LB80 +0.011) read −0.0084 [−0.0224, +0.0054] on its 3,920-deal fresh-seed screen (#1263, 2026-11-09). A candidate
  whose DEV point sits within about one DEV standard error of the bar goes to the screen before anything is built on it;
  when a screen is affordable, a lane may skip the DEV duel and go straight to the screen.

**Window rule (ten-window MC-LCB instrument only)**

The default screen is the duel ("Duel bar" above). This rule applies only to a lane that predeclares the
ten-window MC-LCB instrument.

- Five windows first; extend to ten only when the point exceeds +0.015 and the interval crosses zero.
- A five-window interval spanning zero is INCONCLUSIVE, reported with its MDE80; it supports neither "not large"
  nor "equal" (amendment adopted on #663).
- Five-window MDE80 is about 0.033 on shortlist-era capped screens and about 0.05 on served head-driven screens;
  each readout reports its own. Ten shared-control windows are a nominal read; only fresh held-out deals confirm.

**Predeclared statistics options** (D9, 2026-10-15; code `server/shengji/eval/paired_window_stats.py`; adoption on
HOLD per board #1263). A lane may predeclare either or both before any outcome; otherwise it keeps the frozen
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
