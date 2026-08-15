# Sheng Ji (升级 / Tractor)

**Play it now: https://shengji.fly.dev** — solo vs bots or share a room code
with friends (phones: landscape).

Full-stack implementation of the classic Chinese partnership trick-taking game:
Python rules engine + Monte Carlo AI + FastAPI multiplayer server + React web
UI with Mandarin voice announcements.

## Project state — 2026-08-15

The production bot is **`mc-s0-report-lcb`**, the first policy in this project
to earn a fresh, preregistered superiority result over the previous N=30 MC
bot. In plain English, it lets ordinary MC nominate a possible override, then
rechecks that exact pair on 300 fresh shared simulations and changes its mind
only when a conservative lower bound is positive. On 2,048 new paired deals it
improved signed level utility by `+0.338 +/- 0.068` per round; a matched null
was flat. Fly release 18 preserves release 17's off-event-loop decision
runtime and adds the kitty X-ray only, so search no longer freezes room
interaction and the policy itself remains unchanged.

The last strength campaign is closed without a promoted challenger. The T4
learned-search treatment, S4 point-banking continuation, and combined S6
shuai-pai source all reached independently reviewed `SELECT_NONE` decisions.
Two Pair-aware whole-game attempts produced no terminal evidence: Air timed
out at `0/8` shards and the checkpoint successor failed closed on work
telemetry. One T4 control arm was positive, but it used 14.8% more accepted
worlds and 80.9% more searches than champion, so candidate widening and added
compute remain confounded rather than established as a same-work win.

The current research milestone is **BELIEF-V1**: a typed actor-visible world
model that learns calibrated hidden-card ownership before it is allowed to
change search. Its public/actor/private information contracts are merged; the
B2 offline pipeline is under source review and no corpus, training, test-split
opening, sampler, gameplay, or strength run has started. A separate three-arm
design will measure ballot widening at champion work and at the original T4
control work. See [BACKLOG.md](BACKLOG.md) for the executable queue,
[JOBS.md](JOBS.md) for live fleet state, and [AI_POLICIES.md](AI_POLICIES.md)
for canonical results.

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
                         enumeration, BC/distillation/DMC training
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

- **`mc-s0-report-lcb` (production)** — N=30 determinized MC plus the fresh
  paired report check described above. `mc-strong` is its policy rollback.
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
enumeration, BC + search-distillation + DMC self-play trainers, an
oracle value baseline, and an Elo tournament + human-agreement
validation battery.

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
  bury-search candidates/work account.
- `scripts/analyze_human.py`, `scripts/eval_vs_human.py` — score human
  decisions against the bot / the whole policy ladder.
- `scripts/fetch_fly_logs.sh` — stage, validate, refresh and hash prod logs.
- `python -m shengji.rl.human_shards` — build a fresh replay-audited,
  provenance-bound human play/bury corpus; raw human choices remain proposal
  data until counterfactually validated.


## Project docs

| file | what it holds |
|---|---|
| `RL_PLAN.md` | state of play, key learnings, roadmap, measurement rules |
| `AI_POLICIES.md` | canonical AI results + every policy/toggle and durable conclusion |
| `CORRECTNESS.md` | validation suite, house rules, incident index |
| `incidents/` | postmortems (what happened, why detection was slow) |
| `PERF.md` | profiling, shipped optimisations, ranked gaps |
| `BACKLOG.md` | current milestone, ordered work, blockers and exit gates |
| `JOBS.md` | live fleet job plus compact terminal-job index |
| `MAINTENANCE.md` | daily routine (any session can execute it) |
| `HANDOFF_ACTIVE.md` | compact executable Codex/Claude mailbox |
| `HANDOFF_REVIEW.md` | short active exact-review mailbox; completed ledgers are archived |
| `DEPLOY.md` / `PROTOCOL.md` | hosting + wire protocol |
| `web/README.md` | client architecture, protocol contract, UI invariants |
| `docs_archive/` | compacted history (RL chronology, resolved backlog, old review rounds) |

Top-level documents are reserved for current project, operational, or durable
contract surfaces. A completed one-off experiment spec should be summarized in
its canonical owner and moved to `docs_archive/`; evidence-bound specs remain
in place only while their experiment is live.
