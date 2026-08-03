# Sheng Ji (升级 / Tractor)

**Play it now: https://shengji.fly.dev** — solo vs bots or share a room code
with friends (phones: landscape).

Full-stack implementation of the classic Chinese partnership trick-taking game:
Python rules engine + Monte Carlo AI + FastAPI multiplayer server + React web
UI with Mandarin voice announcements.

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
                         (Monte Carlo search, server default, Elo ~1140),
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
(`curl /healthz` reports the active one). The current ladder, all
measured on mirrored deals (details in `AI_POLICIES.md`):

- **`mc` (default)** — determinized Monte Carlo search over a
  card-counting heuristic; pool Elo ~1140.
- **`rl`** — a neural policy trained by distilling the search's own
  evaluations (no search at inference, ~2ms/decision); passed the
  heuristic tier in one day of training, currently ~70 Elo behind `mc`.
  Needs `uv sync --group rl` + a local checkpoint (`SHENGJI_RL_CKPT`).
- `smart`, `heuristic` — the hand-written tiers below both.

Training pipeline (`server/shengji/rl/`, roadmap and full experiment
log in `RL_PLAN.md`): observation/action encoders, legal-play
enumeration, BC + search-distillation + DMC self-play trainers, an
oracle value baseline, and an Elo tournament + human-agreement
validation battery.

## Debugging & analysis tools

- `scripts/replay.py` — render any game log (`logs/<ROOM>.jsonl`) as a
  full transcript with all hands.
- `scripts/xray.py` / the in-game X-ray (press `x`; needs
  `SHENGJI_DEBUG_TOKEN`) — what the bot sees and would play from any
  position.
- `scripts/analyze_human.py`, `scripts/eval_vs_human.py` — score human
  decisions against the bot / the whole policy ladder.
- `scripts/fetch_fly_logs.sh` — pull prod game logs for the above.


## Project docs

| file | what it holds |
|---|---|
| `RL_PLAN.md` | state of play, key learnings, roadmap, measurement rules |
| `AI_POLICIES.md` | every bot policy + toggle with its measured record |
| `CORRECTNESS.md` | validation suite, house rules, incident index |
| `incidents/` | postmortems (what happened, why detection was slow) |
| `PERF.md` | profiling, shipped optimisations, ranked gaps |
| `BACKLOG.md` | open work, roughly by value |
| `MAINTENANCE.md` | daily routine (any session can execute it) |
| `HANDOFF_REVIEW.md` | external-review thread (Codex <-> Claude) |
| `DEPLOY.md` / `PROTOCOL.md` | hosting + wire protocol |
