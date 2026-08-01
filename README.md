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
server/shengji/ai/       heuristic.py (baseline), memory.py (card counting /
                         void inference), smart.py (memory-aware bot, wins
                         86% vs baseline), env.py (self-play harness with
                         mirrored-deal evaluation), registry.py (named
                         policies; see AI_POLICIES.md)
server/shengji/api/      FastAPI WebSocket server (rooms, bots, per-seat state)
server/tests/            unit tests + randomized self-play soak tests
web/                     React + TypeScript UI (Vite)
PROTOCOL.md              WebSocket protocol contract
```

The engine is authoritative and UI-free; the server maps card instance ids to
codes per seat so hidden information never leaves the server.

## Training a stronger AI (roadmap)

A policy is anything implementing three methods (see `ai/heuristic.py`):
`decide_declare`, `decide_bury`, `decide_play`. The self-play harness in
`ai/env.py` already runs policy-vs-policy games headlessly at ~360 rounds/sec
per core and reports win rates (`evaluate(policy_a, policy_b)`).

Suggested path:
1. Wrap `play_round` in a PettingZoo AEC env: encode hand/trick/trump/points
   as binary features; action space = enumerated legal plays with masking.
2. Self-play PPO (CleanRL or RLlib) with an opponent pool of past
   checkpoints; reward = level change at round end (±gain), with small
   per-trick point shaping to speed early learning.
3. Drop the trained policy into the server: construct the bot in
   `api/server.py` (`Room.bot`) with your model-backed implementation and
   play against it in the UI.
