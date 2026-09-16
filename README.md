# Sheng Ji (升级 / Tractor)

**Play it now: https://shengji.fly.dev** — solo vs bots or share a room code
with friends (phones: landscape).

Full-stack implementation of the classic Chinese partnership trick-taking game:
Python rules engine + Monte Carlo AI + FastAPI multiplayer server + React web
UI with Mandarin voice announcements.

## Project state — 2026-09-16

The live Fly snapshot is **release 28: the JS-M1 joint model as ONE package**
(`/data/models/js-m1-0d17fd03.npz`; policy `mc-shortlist-0d17fd03-w32-r0d610b62-prior-0d17fd03-bury-hybrid-003c2abe49ff`).
One checkpoint now does two jobs. As the **value net** it ranks every legal
action across 32 sampled hidden worlds and hands the incumbent plus four
alternatives to production's full Monte Carlo search (N30 selection, R300
report, heuristic rollouts). Above 1,000 legal actions its own **policy head is
the admission prior**: it runs once per sampled world, and the union of the
per-world top-256 plus production's anchors (about 600 actions, median) is what
the value net ranks, so the exhaustive wide follows that used to take minutes
are gone. Hybrid bury (heuristic candidates, model scoring, MC selection, 2 s
budget) is unchanged. The engine is the compiled fast path.

How it got here (2026-09-15/16, each step on Jerry's explicit go, records in
[DEPLOY.md](DEPLOY.md)): release 25 shipped M1 plus a separate policy prior and
stalled every bot turn (the server's turn snapshot could not deep-copy the NumPy
prior); it was rolled back within the hour, fixed, and redeployed as release 27;
release 28 replaced the two files with the single joint checkpoint.

**Evidence behind the current policy** (details in
[AI_POLICIES.md](AI_POLICIES.md#production-contract); readouts in the scaling
log and the search atlas):

- M1 (`3cb9cd62`, a residual-trunk MLP on the 176k afterstate corpus) confirmed
  on ten fresh windows against the release 24 recipe, `+0.0212 [+0.0036, +0.0387]`
  signed levels per round; twenty fresh windows of the M1 family pooled
  `+0.0140 [+0.0026, +0.0254]`.
- The policy prior changed M1's outcomes by `−0.0003 [−0.0017, +0.0012]` on paired
  seeds (no resolved difference; this is a paired estimate, not an equivalence
  test) and, in the observed windows, cut the latency tail: 0 decisions over
  60 s in 365,414 fresh-deal decisions against 161 (and 7 cap hits) for the old
  recipe; at threshold 1,000 the longest decision in 182,494 was 9.9 s at 0.60×
  the old decision wall.
- JS-M1 (`a5248cc5`): M1's recipe trained from scratch with a policy head on all
  20.3M root decisions. Offline it beats M1 on the outcome head (val CE 0.5957 vs
  0.5975) and its head is non-inferior to the separate prior on four of five
  strata. In play as one net (five capped windows) it read
  `+0.0239 [+0.0005, +0.0472]` against the release 24 recipe and
  `+0.0057 [−0.0163, +0.0277]` paired against release 27 at the same wall. No
  ten-window or fresh-seed read yet.
- Releases 27 and 28 passed the decision-identity gate (the NumPy packages
  reproduce the Torch checkpoints' decisions) and the server-path smoke (the
  server can take bury and play turns with the built bot), both in
  `server/scripts/`. Release 25 passed the gate alone and stalled live; the
  smoke was written because of it and has preceded every deploy since.

Older lanes (BELIEF R4/R5, PT-Sol/Luna teachers, D64) are closed and remain
lessons, not policies. See [RL_PLAN.md](RL_PLAN.md) for the decision tree,
[BACKLOG.md](BACKLOG.md) for the queue, [AI_POLICIES.md](AI_POLICIES.md) for
measured results, and [RESEARCH_PRINCIPLES.md](RESEARCH_PRINCIPLES.md) for the
rules those results produced.

## Quick start

```bash
# 1. Build the frontend (once, or after UI changes)
cd web && npm install && npm run build && cd ..

# 2. Run the server (serves the built UI at http://localhost:8000)
cd server && uv sync && uv run shengji-server
```

Open http://localhost:8000, create a room, add 3 bots (or share the room code
with friends on your network), and start. For frontend development use
`npm run dev` in `web/` (Vite on :5173, talks to the server on :8000).

Tests: `cd server && uv run pytest`.
Headless bot-vs-bot evaluation: `uv run python -m shengji.ai.env`.

## Rules implemented (standard 4-player, 2 decks)

- Teams 0+2 vs 1+3, levels 2→A; the banker team's level is the trump rank.
- Live dealing phase: cards are dealt one at a time and any player may
  declare mid-deal by revealing trump-rank card(s) (pair beats single, joker
  pair declares no-trump and beats both), with a short grace window after the
  last card for over-declarations. No declaration → trump is flipped from
  the kitty. First round's first declarer becomes banker.
- Banker takes the 8-card kitty and buries 8.
- Pairs, tractors (consecutive pairs, trump-aware adjacency incl. rank cards
  and jokers), and throws (甩牌) — an invalid throw is forced down to its
  lowest component.
- Follow rules: follow suit with matching count; pairs must cover pair leads;
  tractor leads oblige an in-suit tractor of that length when you hold one;
  void hands may trump with a shape-matching play.
- Points: 5s=5, 10s/Ks=10 (200 total). Attackers win at 80. If attackers
  take the last trick, kitty points are multiplied by 2 × the size of the
  winning play (single ×2, pair ×4, 2-pair tractor ×8).
- Scoring: attackers 0 → banker +3, <40 → +2, <80 → +1; attackers 80+ take
  the deal and gain (points−80)/40 levels. The game is won by successfully
  **defending** at level A — attackers who win at A take the deal and must
  then hold their A.

House-rule simplifications (v1): throws are checked against all three other
hands with no 10-point penalty; pair obligations for multi-component throws
use the pair-count rule.

## Layout

```
server/shengji/engine/   cards, combos (tractor decomposition), legality, round, game
server/shengji/ai/       policies: heuristic.py (baseline), smart.py +
                         memory.py (card-counting heuristic), mcbot.py
                         (Monte Carlo search; source fallback, while Fly pins
                         mc-s0-report-lcb),
                         registry.py + env.py + tournament.py (evaluation;
                         ladder and all measurements in AI_POLICIES.md)
server/shengji/rl/       learned-policy pipeline: encoder, action
                         enumeration, afterstate value model
                         (roadmap in RL_PLAN.md)
server/shengji/api/      FastAPI WebSocket server (rooms, bots, per-seat state)
server/tests/            unit tests + randomized self-play soak tests
web/                     React + TypeScript UI (Vite)
PROTOCOL.md              WebSocket protocol contract
```

The engine is authoritative and UI-free; the server maps card instance ids to
codes per seat so hidden information never leaves the server.

## The AI

A policy is anything implementing three methods (`decide_declare`,
`decide_bury`, `decide_play`); the server picks one via `SHENGJI_BOT`
(`curl /healthz` reports the active one). Current evidence, with provenance
and promotion caveats in `AI_POLICIES.md`:

- **JS-M1 joint model, one package (live PLAY + PRIOR + hybrid BURY, release 28)** —
  the network proposes (value head over the exhaustive legal set on 32 sampled
  worlds; policy head prunes decisions above 1,000 legal actions), full MC
  rollouts and the report fold still decide. Registered from the `fly.toml`
  environment by `server/shengji/ai/registry.py`; the name binds the package
  SHA, the recipe and the prior settings.
  [Architecture and evidence](AI_POLICIES.md#production-contract).
- **M1 + policy prior v2 (release 27, rollback)** — the same design with two
  files (value package `12ce4415`, prior package `b9ff76c9`).
- **`mc-s0-report-lcb` (the MC-LCB search; screen baseline and deep rollback)** —
  N=30 determinized MC plus the fresh paired report check described above.
- **`mc` (source fallback, not production)** — the older N=10 determinized
  search policy.
- **`rl-override-v11pair` (experimental)** — the best learned milestone beat
  SmartBot 57.7%, but the corrected direct-v2 screen lost to current search and
  selected none. Keep it only as a bounded proposal/ranking and teacher
  diagnostic; it is not a scalar leaf or production candidate.
- **Direct-Q and Suphx O0 (experimental, closed)** — both learned something,
  but each failed its own preregistered robustness/held-out gate. They inform a
  fresh learner-mechanism experiment; neither is deployable or extendable from
  its inspected result.
- **`smart`, `heuristic`** — the hand-written baselines.

The objective is verified bot strength, not RL or search complexity for its
own sake. Screens choose what deserves confirmation; only fresh paired games
against the named live champion establish a new strength claim.

Training pipeline (`server/shengji/rl/`, roadmap and full experiment
log in `RL_PLAN.md`): observation/action encoders, legal-play
enumeration, the afterstate value model behind the `mc-cwv-*` bots, the
trajectory/oracle screens under `server/shengji/train/`, and an Elo
tournament + human-agreement validation battery.  The BC/distillation/DMC,
suphx and belief lanes were removed on 2026-09-05 (tag
`archive/code-lanes-pre-cleanup-20260905` keeps them).

## Evaluation glossary

- **Paired cluster:** the same deal is played with fixed seat/team flips so
  policy differences are compared on shared luck rather than unrelated games.
- **Signed level utility:** round outcome measured in levels from one named
  team's perspective; it is not the same as game win rate.
- **Report fold:** fresh simulations used only to re-evaluate a decision chosen
  on a separate selection fold.
- **LCB:** lower confidence bound. A positive LCB means the conservative edge,
  not merely the noisy point estimate, is above zero.
- **Screen:** a bounded design-selection experiment. It cannot by itself
  promote a policy.
- **Confirmation:** a fresh, preregistered paired evaluation of one frozen
  candidate against a named champion and controls.
- **SELECT NONE:** the registered gate did not authorize a candidate. It does
  not necessarily mean every observed point estimate was negative.

## Debugging & analysis tools

- `scripts/replay.py` — render any game log (`logs/<ROOM>.jsonl`) as a
  full transcript with all hands.
- `scripts/xray.py` / the in-game X-ray (press `x`; needs
  `SHENGJI_DEBUG_TOKEN`) — what the bot sees and would play from any
  position, including the banker's chosen kitty bury and any available
  bury-search candidates/work account. The in-game panel also separates W32
  model nominations (acting-team signed levels), MC selection estimates
  (attacker points), and the paired report-gap decision (acting-team points).
  It labels the checkpoint, recipe, search work and measured times. Missing
  uncertainty is shown as unavailable, not zero.
- `scripts/fetch_fly_logs.sh` — stage, validate, refresh and hash prod logs.
- `python -m shengji.rl.human_shards` — build a fresh replay-audited,
  provenance-bound human play/bury corpus; raw human choices remain proposal
  data until counterfactually validated.

For the in-game panel, set `localStorage.setItem("shengji.debug", "<token>")`
in browser devtools using the server's `SHENGJI_DEBUG_TOKEN`, then press `x`
on your play turn. It evaluates an **isolated snapshot**, not a historical
bot decision or a continuously updating view; reopen it for a new position.
The report gap is challenger minus incumbent, so a positive mean does not
guarantee an override: with W32's LCB rule, the displayed decision statistic
(a lower bound) must clear the gain threshold.
Xray uses the same model-worker limit as gameplay and returns a busy message
instead of queuing extra searches. It does not change the live bot RNG, reveal
sampled hidden hands, or establish that the bot planned a later sequence.


## Project docs

| file | what it holds |
|---|---|
| `RL_PLAN.md` | state of play, key learnings, roadmap, measurement rules |
| `AI_POLICIES.md` | canonical AI results + every policy/toggle and durable conclusion |
| `CORRECTNESS.md` | validation suite, house rules, incident index |
| `incidents/` | postmortems (what happened, why detection was slow) |
| `PERF.md` | engine/search speed rules, dated baselines, shipped optimisations (live perf work: issue #208) |
| `BACKLOG.md` | current milestone, ordered work, blockers and exit gates |
| `AGENTS.md` | automatically loaded execution, review, parallelism and long-run discipline |
| `CODEX_WORKFLOW.md` | project-scoped Codex setup and exact rollback |
| `RESEARCH_PRINCIPLES.md` | durable scientific doctrine, estimands and evidence boundaries |
| `MAINTENANCE.md` | daily routine (any session can execute it) |
| `HANDOFF_ACTIVE.md` | compact current gate summary, fleet, and open review asks; history is rotated to `docs_archive/` (removal under discussion with Codex) |
| `HANDOFF_REVIEW.md` | append-only exact-review ledger on canonical `main`; its existing authenticated historical rotation is preserved in `docs_archive/` |
| `DEPLOY.md` / `PROTOCOL.md` | hosting, release records and rollbacks + wire protocol |
| `W32_FLY_SERVING.md` | the NumPy serving path: packages, identity gate, server-path smoke, healthz |
| `docs/scaling_log/` | the scaling log page: every value model, its offline metrics and screen results (built from `models.py`) |
| `web/README.md` | client architecture, protocol contract, UI invariants |
| `docs_archive/` | compacted history (RL chronology, old job snapshots, resolved work/reviews) |

Top-level documents are reserved for current project, operational, or durable
contract surfaces. A completed one-off experiment spec should be summarized in
its canonical owner and moved to `docs_archive/`; evidence-bound specs remain
in place only while their experiment is live.
