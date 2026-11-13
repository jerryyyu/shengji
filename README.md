# Sheng Ji (升级 / Tractor)

**Play it now: https://shengji.fly.dev** — solo vs bots or share a room code
with friends (phones: landscape).

The classic Chinese partnership trick-taking game: Python rules engine, Monte
Carlo AI guided by a learned model, FastAPI multiplayer server, and React web UI
with Mandarin voice announcements.

## The production bot

**Live: release 52** (since 2026-11-09, Fly v64; [DEPLOY.md](DEPLOY.md#current-production) has the record and
rollback). It is release 51 plus the combo51 search rules (elt, elm, els1600, wht, rcec; see the list below), with the
same packages and budgets. Against release 51 it measured +0.0438 levels/round [+0.0381, +0.0497] over 7,840 fresh
paired deals. New duels and screens compare against release 52 as served.

How the bot plays: a belief model draws 64 hidden-hand worlds, the policy admits 8 candidate plays, and the value head
scores each candidate in every world; at 7 cards or fewer an exact endgame search takes over. The model owns
declaration, bury and card play; the heuristic is the anchor and the fallback.

Earlier releases, newest first (full history in [DEPLOY.md](DEPLOY.md) and [AI_POLICIES.md](AI_POLICIES.md)):

- **51**: release 50 with the lead confirmation (lcc32) off, cheaper to serve at a small measured cost; the rollback target.
- **50**: G3 value, FT1 card-play prior, B1a belief and belief-drawn bury worlds (bbw).
- **49**: two lead rules, the singleton challenger (sc8) and the lead confirmation (lcc32).
- **48**: the S58 belief package, dtrx and the greedy-finished value leaf (lgf).
- **46**: belief-model worlds, the exact endgame at 7 cards and value-guided first-round declaration.
- **45**: the SMV3 outcome-head package in the policy/value search, with the div, rc, tb, la and dtr search rules and the wide value-only bury.

<img src="docs/visuals/decision-steps.svg" alt="One decision, four steps, with one live decision as the example: a bot leading with 7 cards left. The numbers are real; the shades, tiles and tree shape are illustrative. Step 1, belief: one call on the public history returns each card&#39;s odds of being in each of the 4 hands, drawn as a small heatmap; deals are sampled from it, drawn as 66 tiles with 2 crossed out for breaking earlier play, leaving 64 sampled deals. Step 2, prior: one call on 64 positions returns a score per card; the 64 legal plays are drawn as bars and the top 8 are admitted, the jack of diamonds at log-odds −0.06 and the ace of clubs at −0.22 first. Step 3, value: 4 calls of 128 positions score each of the 8 plays in each of the 64 deals, drawn as an 8 by 64 heatmap with a row-mean column; the best average was the ace of clubs at 1.799. Step 4, endgame: with 7 cards or fewer, no model is called and each deal is solved exactly by a game tree with all hands face up and pruned branches, and the per-deal results are averaged; it switched to the jack of diamonds, 1.797 against 1.719 for the ace of clubs. The bot played the jack of diamonds in 0.49 seconds. All models run in NumPy on the server CPU, with a 3 second budget per decision; the trump call and the bury reuse the value model." width="100%">

### How the search works

**Belief sampling.**
- The belief model (bw) reads the public history and gives, for every hidden card copy, the probability that each other hand or the kitty holds it. The probabilities are masked to the holders the public facts allow (voids, declared cards), rescaled so each holder's expected count matches its size, and drawn copy by copy in random order, each copy only onto a holder that leaves the rest of the deal completable.
- A drawn world is rejected when an earlier follow would have been illegal from the hand it gives that seat at the time (whl, whd), when an earlier accepted throw would have been refused (wht), or when a throw refused this round would not be refused with the same forced card (rc; the record of refusals is updated after every play, rcec).
- The search keeps 64 worlds. The history tests apply to the first 512 draws and the plain sampler fills any shortfall after 2,560. If the belief model errors or its preparation takes over 0.25 s, the decision draws from the Monte Carlo sampler under the same tests.

**Candidates.**
- Legal plays are enumerated (up to 4,000) with the heuristic's play included. The prior runs once on the 64 root positions, one per world; a play's score is the sum of its cards' log-odds, averaged over the worlds.
- 8 plays are admitted: the heuristic's play first, then the best scores, at most 2 per shape and no near-duplicate throws (div). On a low non-trump single lead, the first slot goes to the strongest one-suit pair or tractor (la).
- On a lead with more than 7 cards in some hand, singles left off the ballot are probed on 8 worlds, and the best one takes the last slot if it beats every admitted play there (sc8).

**Value pass.**
- One position is a candidate played in one world, with the rest of the trick finished: each remaining seat plays whichever of the prior's top 4 follows and the heuristic's follow the value model rates best for its team (lgf). Where an exact stage will run, or once 2 s have passed, the heuristic finishes the trick instead (lgfx, lgfd2000).
- The value model scores the 512 positions in batches of 128 as expected signed levels for the bot's team, and the best mean over the 64 worlds wins. Plays within 0.02 levels of the best are separated by trick points won (tb).
- A lead throw refused in every world with the same forced card is dropped and the rest re-selected (dtr); after an exact pass the re-selection may not lower the exact mean (dtrx).

**Exact endgame.**
- When every hand holds 7 cards or fewer, each admitted play is also solved in each of the 64 worlds with all hands face up: partnership minimax to the round's end with alpha-beta pruning and a transposition table (ele, ed7 for leads, xf7 for follows). The per-world outcomes, in signed levels, are averaged over the worlds.
- A lead solves its own first trick by minimax (elm) and replaces the value pass's lead only on a strictly higher exact mean (elt), within 1.6 s (els1600); a follow likewise switches only on a strictly higher mean.
- The lead stage starts only in the first half of the budget, both stages stop by 80% of it, and a stage that does not finish leaves the value pass's choice.

**Declaration and bury.**
- Where the heuristic would declare, at the last chance, or at any chance in round 1 (vdef), each option and passing are scored on 64 deals drawn uniformly around the seat's hand and the current declaration, each with the heuristic's bury and first trick; the best replaces the heuristic's choice only if strictly higher (vd).
- The bury scores up to 64 candidate kitties (the heuristic's, structured alternatives and single-card swaps) on 32 belief-drawn worlds and keeps the best mean (bwv, bbw).

**Budget and fallbacks.** The heuristic decides first. Card play and declaration have 3 s per decision and the bury 2 s, checked between draws and model batches; past the budget or on any error the bot plays the heuristic's choice.

### The models

All three are trained in PyTorch, exported to `.npz` and run in NumPy on the server CPU; value positions go in batches of 128. On Fly, a release 52 decision takes p95 0.855 s with one game running ([DEPLOY.md](DEPLOY.md#latency)).

- **Belief: B1a (`028131a0`), a transformer, 3.2M parameters.** A causal 4-layer encoder (width 192, 4 heads) reads the round's earlier plays as tokens: cards, seat, trick, position in the trick, led suit and attempted throws. One query per card (54) cross-attends to that history through 4 layers, then the cards attend to each other in one more; a 2-layer MLP (256 wide) over 1,115 public features adds to the output. The output is 54 × 4 logits (next player, partner, previous player, kitty), masked to the holders the public facts allow and turned into probabilities by a softmax at the package's calibration temperature, 1.019, which flattens them slightly; no setting changes it in release 52. It is trained to predict each hidden card's true holder: S58 fine-tuned on 10.3M decisions from the Y self-play rounds.
- **Value: G3 Stage A (`f4f4127e`), a residual MLP, 620k parameters.** 833 inputs (561 public features, the world's complete deal as 5 × 54 card counts for the four hands and the kitty, and 2 for the perspective) go through a linear stem to width 165, four residual blocks (LayerNorm, a 330-wide ReLU layer, back to 165, added to the block's input), and a final LayerNorm and ReLU. The head gives 204 outcome classes; their softmax, weighted by each class's signed level, is the expected signed level for the scoring seat's team. It is trained with cross-entropy on round outcomes from 200k Y self-play rounds, warm from SMV3's trunk.
- **Prior: FT1 (`1fa201b2`), the same residual MLP with a 54-card policy head.** It reads one root position per sampled world and returns 54 card log-odds; the search uses them raw, with no softmax or temperature, summed over a play's cards. It is the policy net fine-tuned toward about 37.8k expert-search labels. The prior package's value head and the value package's policy head are not used.

Rule tokens used in the figures and tables:

- **div**: diversify candidates (at most 2 of the same shape)
- **rc**: keep only worlds where this round's refused throws stay refusable
- **rcec**: record each refused throw after every committed play, not only on the bot's own turns (release 52)
- **la**: lead anchor: on a weak-single lead, admit the strongest pair/tractor as candidate zero
- **tb**: tie-break near-equal moves by points won this trick
- **dtr**: drop a lead throw the engine would refuse in every world
- **vd**: value-guided trump declaration
- **vdef**: in round 1, consult the value head at every declare chance
- **whl / whd**: sampled worlds must be consistent with every earlier follow (history-legal)
- **wht**: sampled worlds must also leave every earlier accepted throw unrefusable (release 52)
- **bw**: hidden hands proposed by the belief model (B1a since release 50; S58 in releases 48 and 49, S17 in release 46)
- **ele / ed7 / xf7**: exact endgame search for leads and follows at ≤7 cards
- **elt / elm / els1600**: the exact lead keeps the baseline lead unless strictly better, solves its own first trick by minimax, and stops at 1.6 s (release 52)
- **bwv**: wide value-only bury (64 candidate kitties)
- **dtrx**: dtr never overrides a complete exact lead stage (release 48)
- **lgf / lgfx / lgfd2000**: finish the trick with greedy replies before the value pass; skip it where an exact stage is eligible; stop it past 2 s (release 48)
- **bbw**: the wide bury scores its candidate kitties on belief-drawn worlds (release 50)
- **sc8**: singleton challenger: a single the policy left off the ballot can take its last slot (release 49)
- **lcc32**: lead confirmation: screen extra leads up to a 32-action total budget on the base worlds, then confirm at most two challengers on fresh worlds before replacing the served lead (releases 49 and 50); off since release 51

<img src="docs/visuals/release-ladder.svg" alt="Forest plot of served results by release in levels per round with 95% confidence intervals; release 52 (combo51: elt, elm, els1600, wht, rcec) vs 51 is +0.0418 on the screen and +0.0438 on the confirmation; release 51 (lead confirmation off) vs 50 is −0.0133 on the cloud confirmation lccC and +0.0079 on the M5 Ultra duel loo, not measured on Fly; release 50 vs 49 is +0.0695 on the screen (one-sided 80% lower bound +0.0631) and +0.0618 on the confirmation; release 49 vs 48 is +0.0270 on the screen and +0.0306 on the confirmation (releases 49 to 52: paired head-to-head duels, a different instrument); release 48 vs 46 is +0.0765 on the screen and +0.0843 on the confirmation; release 46 vs 45 is +0.2167 on the screen and +0.2284 on the confirmation; every earlier step lies between +0.01 and +0.05. Each rule token is glossed under its row. Rows up to release 48 are contrasts through a common MC-LCB control; separate contrasts; not additive." width="100%">

**Served results** (signed levels per round, 95% CI; each row names its method: indirect contrasts through a common MC-LCB control unless the row says paired duels):

| change | against | result | reading | vs Sol, actor-only | vs PT-Sol |
|---|---|---|---|---|---|
| combo51: elt + elm + els1600 + wht + rcec (release 52; paired head-to-head duels) | release 51 | screen +0.0418 [+0.0332, +0.0506]; confirmation +0.0438 [+0.0381, +0.0497] (7,840 fresh deals) | SCREEN_PASS and CONFIRMED (combo51, combo51C), M5 Ultra; Fly strength not measured | — | — |
| lead confirmation off (release 51; paired head-to-head duels, lcc off − on inside release 50) | release 50 | lccC −0.0133 [−0.0232, −0.0033] (confirmation, cloud); loo +0.0079 [−0.0069, +0.0221] (M5 Ultra) | KEEP_LCC (lccC) and DROP_SAFE (loo): the reads disagree; shipped for CPU (Fly ×0.552 per play, S91) on Jerry's word; Fly strength not measured | — | — |
| G3 Stage A value + FT1 prior + B1a belief + bbw (release 50; paired head-to-head duels) | release 49 | screen +0.0695 (one-sided 80% lower bound +0.0631); confirmation +0.0618 [+0.0507, +0.0729] | SCREEN_PASS and CONFIRMED (cbaf arm a, cbaC); four changes at once; AI_POLICIES ladder row 19 has the one within-run attribution | — | — |
| sc8 + lcc32 (release 49; paired head-to-head duels, not the MC-LCB scale) | release 48 | +0.0270 [+0.0135, +0.0408]; confirmation +0.0306 [+0.0167, +0.0441] | DEV_PASS and CONFIRMED (combo3y, combo3yc) | — | — |
| S58 belief + dtrx + guarded greedy finish (release 48) | release 46 | +0.0765 [+0.0571, +0.0958]; confirmation +0.0843 [+0.0575, +0.1111] | POSITIVE and CONFIRMED (r48cloud, r48confirm) | — | — |
| the combo (belief worlds + D7/X7 exact endgame + vdef) | release 45 | +0.2167 [+0.1923, +0.2412]; confirmation +0.2284 [+0.2046, +0.2521] | POSITIVE and CONFIRMED (v92combo45, v92c) | +0.55 [+0.25, +0.90] (S47) | pending (S47-PT) |
| wide value-only bury K=64 (release 45) | release 44 | +0.0488 [+0.0286, +0.0690] | POSITIVE, one ten-window screen on first-round deals, not confirmed (v76bwv44) | — | — |
| value-guided declaration (release 44) | release 43 | +0.0497 [+0.0379, +0.0615] first-round; +0.0352 [+0.0233, +0.0471] later-round | POSITIVE in both populations, ten windows each (v70vd43, v71vd43lr) | — | — |
| doomed-throw swap / re-select (releases 42, 43) | release 38 / 42 | interval spans zero | correctness fixes, no strength claim | — | — |
| div + rc + tb | release 36 | +0.0461 [+0.0242, +0.0681] | CONFIRMED, ten fresh windows (#676) | — | — |
| + la | div + rc + tb | +0.0106 [+0.0006, +0.0205] | POSITIVE incremental (not a confirmation): small, ten windows, lower bound near zero (#676) | — | — |
| SMV3 outcome head (release 36) | release 30 | +0.0393 [+0.0033, +0.0752] | predeclared confirmation (#663) | +0.45 [0.00, +0.80] (#355); 0.00 [−0.40, +0.35] (S47) | +0.30 [−0.20, +0.80] (#355) |
| policy/value search (release 29) | release 28 | +0.049 [+0.003, +0.095] | five windows; card play +0.086 [+0.042, +0.131] | +0.50 [+0.15, +0.90] (#355) | +0.45 [−0.10, +0.95] (#355) |

The two Sol columns come from a separate instrument. The release's recipe plays card play only against the GPT-5.6
Sol LLM opponent, on 10 deals × 2 mirrored roles. Actor-only Sol sees one seat's hand; PT-Sol sees every hand. Each
cell is bot minus Sol in signed levels per round, with a deal-cluster 95% CI. These numbers are not on the screen
scale and do not rank the releases
([details](AI_POLICIES.md#the-ladder-every-production-change-and-what-it-measured)).

The exact contract, the caveats on these reads, what was tried and not taken, and every earlier release:
[AI_POLICIES.md](AI_POLICIES.md#production-contract) and its
[ladder](AI_POLICIES.md#the-ladder-every-production-change-and-what-it-measured).
Rollback and gates: [DEPLOY.md](DEPLOY.md). Every screen: [Atlas v2](docs/atlas_v2/registry.json).
Open work: the board issue (see AGENTS.md) and [RL_PLAN.md](RL_PLAN.md#planned-work).

## How a strength change ships (current workflow)

<img src="docs/visuals/how-a-change-ships.svg" alt="How a change ships: idea, DEV test with a predeclared bar, screen duel of 3,920 seat-swapped deals, confirmation duel of 7,840 fresh deals, latency gate on one core, reviewed release PR with green CI, deploy on Jerry&#39;s word, Fly check. Inside one duel, the candidate plays the served release head to head, each deal twice with the seats swapped; example cbaC, a confirmation of the release-50 candidate: +0.0618 [+0.0507, +0.0729] levels per round vs release 49 as served, CONFIRMED because the mean is at least +0.005 and the 95% lower bound is above zero." width="100%">

Screens and confirmations are paired, seat-swapped head-to-head duels against the served release (release 52):
each deal is played twice with the seats swapped, and the read is signed levels per round with a deal bootstrap.
A screen of 3,920 deals passes when the mean is at least +0.005 and the one-sided 80% lower bound is above zero; a
screen pass earns a 7,840-deal fresh-seed confirmation (mean at least +0.005, 95% lower bound above zero) or a
place in a combination. Release still needs the confirmed duel, Fly timing and Jerry's word. The rules and their pass rates:
[RL_PLAN.md](RL_PLAN.md#operating-modes-rigor-tiers) ("Duel bar"). The ten-window screens through 2026-10-25 used the
older instrument: candidate and release each played the same fixed MC-LCB control over ten 520-cluster windows,
and the result was the difference. Rows of the ladder come from different eras and instruments, so read each alone.

## Quick start

```bash
# 1. Build the frontend (once, or after UI changes)
cd web && npm install && npm run build && cd ..

# 2. Run the server (serves the built UI at http://localhost:8000)
cd server && uv sync && uv run shengji-server
```

Open http://localhost:8000, create a room, add 3 bots (or share the room code
with friends on your network), and start. For frontend development, run
`npm run dev` in `web/` (Vite on :5173, talks to the server on :8000).

Tests: `cd server && uv run python scripts/test_checkout.py --engine pure -- -q`.
The entrypoint anchors imports to its own checkout, prints the source and engine,
and checks both before pytest starts. It also works with a shared environment's
Python from another working directory; pass the absolute script path. Use
`--engine compiled` after building that checkout's extension; missing native
code fails instead of silently counting pure coverage. Pure mode unsets
`SHENGJI_FAST` (setting it to `0` is not sufficient).

For a small, model-free producer-to-consumer diagnostic rehearsal:
`uv run python scripts/test_checkout.py --engine pure -- -q tests/test_m9_readout_persistence_roundtrip.py`.
This exercises synthetic collection, persisted panels and final summarization;
it is not a real-model qualification or scientific run. Frontend checks:
`cd web && npm ci && npm run lint && npm test && npm run build` (from repo root).
Headless bot-vs-bot evaluation: `uv run python -m shengji.ai.env`.

## Rules implemented (standard 4-player, 2 decks)

- Teams 0+2 vs 1+3 climb levels 2 to A; the banker team's level is the trump rank.
- Live dealing: anyone may declare mid-deal by revealing trump-rank card(s).
  A pair beats a single; a joker pair declares no-trump and beats both.
  A short grace window allows over-declarations. With no declaration, trump
  is flipped from the kitty. The first round's first declarer becomes banker.
- Banker takes the 8-card kitty and buries 8.
- Pairs, tractors (consecutive pairs, trump-aware adjacency incl. rank cards
  and jokers) and throws (甩牌); an invalid throw is forced down to its lowest
  component.
- Follow suit with matching count; pairs must cover pair leads; a tractor lead
  obliges an in-suit tractor of that length if you hold one; a void hand may
  trump with a shape-matching play.
- Points: 5s=5, 10s/Ks=10 (200 total). Attackers win at 80; taking the last
  trick multiplies kitty points by 2 × the size of the winning play.
- Scoring: attackers at 0 give the banker +3, under 40 +2, under 80 +1;
  attackers at 80+ take the deal and gain (points−80)/40 levels. A game is
  won by **defending** at level A. A room then plays on: the winning team
  scores a game and both teams restart at the room's starting level, which the
  host picks before the first deal.

House rules (v1): throws are checked against all three other hands with no
10-point penalty; pair obligations for multi-component throws use the
pair-count rule.

## Layout

```
server/shengji/engine/   cards, combos (tractor decomposition), legality, round, game
server/shengji/ai/       policies: heuristic.py, smart.py + memory.py (card-counting
                         heuristic), mcbot.py (the Monte Carlo search), cwv_numpy.py
                         (the Torch-free package runtime), refusal.py (refusal-aware
                         world sampling), registry.py (SHENGJI_BOT names are derived
                         from the fly.toml env, never hand-written)
server/shengji/train/    pv_search_policy.py + policy_value_search.py (the served play
                         search, value declare and wide bury), cwv_bury_policy.py (hybrid
                         bury), the shortlist-era bots, screens
server/shengji/rl/       encoders, action enumeration, the value/policy model, trainer
server/shengji/harvest/  self-play trajectory corpora (the training data)
server/shengji/eval/     diagnostic panels, readers and the tactical fixture runner
server/shengji/api/      FastAPI WebSocket server (rooms, bots, per-seat state)
server/scripts/          export_cwv_numpy.py, cwv_serving_gate.py, cwv_serving_smoke.py,
                         replay.py, xray.py
server/tests/            unit tests + randomized self-play soak tests
web/                     React + TypeScript UI (Vite)
PROTOCOL.md              WebSocket protocol contract
```

The engine is authoritative and UI-free; the server maps card instance ids to
codes per seat so hidden information never leaves the server.

## Other policies in the registry

- `mc-s0-report-lcb`: the bare MC-LCB search; the common control of the ten-window screens through
  2026-10-25 (duels have no common control) and the deep rollback.
- The shortlist-era packages (releases 22–28): registered rollbacks (order in [DEPLOY.md](DEPLOY.md)).
- `smart` and `heuristic`: the hand-written baselines.

Closed lanes (PUCT with the heads, root allocation, the BELIEF and privileged-teacher
teachers, direct-Q, Suphx O0) are lessons in [AI_POLICIES.md](AI_POLICIES.md) and
[RL_PLAN.md](RL_PLAN.md), not policies. The G1 grid trunk, a served null in gen 4, came back as the
C14 training run, which closed inconclusive (v96c14e11); the open rows are on the board (RL_PLAN "Planned work").

## Debugging & analysis tools

- `scripts/replay.py` — render any room log (`logs/<ROOM>.jsonl`) as a full
  transcript with all hands.
- `scripts/xray.py` / the in-game X-ray (press `x`; needs
  `SHENGJI_DEBUG_TOKEN`) — what the bot sees and would play from any position,
  on an isolated snapshot (the live bot's RNG is untouched). It decodes
  shortlist-era records (W32 nominations, MC selection estimates, the report-gap
  decision). For the pv-search bot it shows the pick and the bot's memory, not
  the admitted candidates' value means.
- `scripts/fetch_fly_logs.sh` — stage, validate, refresh and hash prod logs.
- `python -m shengji.rl.human_shards` — build a replay-audited human play/bury
  corpus (raw human choices are proposal data until counterfactually validated).

## Project docs

| file | what it holds |
|---|---|
| `AI_POLICIES.md` | production contract, measured policies, evidence and lane rules |
| `RL_PLAN.md` | research plan, key learnings, measurement rules |
| `DEPLOY.md` | release records, rollbacks, gates |
| GitHub issue #1263 + topic issues | the live investigation board and work queue (predecessors #1075, #707, #679, closed) |
| `docs/atlas_v2/` | every screen since release 29 and the era's models (`registry.json`) |
| `docs/scaling_log/` | models with their offline metrics through 2026-10-02; engine and search speed (with issue #208). Later models (C15, S58, FT1, G3 Stage A, B1a) are in Atlas v2's models table |
| `docs/EXTERNAL_SSD.md` | what lives on the external SSD (corpora, backups) and its rules |
| `incidents/` / `server/tests/` | postmortems; the validation suite |
| `AGENTS.md` | execution discipline and agent orchestration |
| `HANDOFF_REVIEW.md` | frozen authority markers (#674) |
| `PROTOCOL.md` / `web/README.md` | wire protocol; client architecture |
| `BACKLOG.md` | deprecated; see #1263 |
| `docs_archive/` | compacted history: closed lanes, old designs, rotated ledgers |

Top-level documents hold only current project, operational or durable contract
surfaces. Completed one-off specs are summarized in their owner and moved to
`docs_archive/`.
