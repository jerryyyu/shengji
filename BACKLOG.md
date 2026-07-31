# Backlog

Working list of improvements we've discussed. Roughly ordered by value within
each section; strike or move items as they land.

## Rules correctness (from comparison with rbtying/shengji)

- [ ] **Defend-at-A game-over rule**: game should end only when a team *defends*
      (wins as banker) at level A. Today either team winning at A ends the game —
      attackers at A should instead take over the deal and have to defend.
      (`engine/game.py`, blocked on: audit results landing first)
- [ ] **Format-scaled kitty multiplier**: last trick won by attackers should
      multiply kitty points by 2×(size of winning play) — single ×2, pair ×4,
      2-pair tractor ×8 — instead of flat ×2. (`engine/round.py`)
- [ ] Apply findings from the engine + server/frontend audit agents (pending).

## Features

- [ ] **Sound effects + Chinese voice announcements** ("红桃二" on declaration,
      trick-win chime, turn ding). Plan: offline TTS-generated clips (edge-tts,
      zh-CN) in `web/public/sounds/` named by card code; shared AudioContext
      unlocked on first tap; announcement queue; mute/volume in localStorage.
      CC0 pack for table SFX.
- [ ] **Spectator mode**: join a full room as a watcher (server: read-only seat
      that gets states with no hand; UI: hide action bar).
- [ ] **LLM commentator / coach mode**: local model (Ollama + Qwen) narrates bot
      reasoning from Memory state (voids, boss cards, points); async so latency
      is free. Coach variant: compare human play vs bot recommendation.
- [ ] Bot takeover for disconnected players (currently the game waits for
      reconnect; after a grace period a bot should play the seat).
- [ ] Trick history viewer in the UI (engine already records `Round.history`).

## AI / training

- [ ] **Mirrored-deal evaluation**: same shuffle with teams swapped, halves the
      variance of `evaluate()`. Cheap and improves every future benchmark.
- [ ] **RL Phase 0**: profile + speed up headless env (`ai/env.py`) for
      self-play throughput; target thousands of games/sec across processes.
- [ ] RL Phases 1-4 (DouZero-style Deep Monte Carlo): encode obs (Memory as
      compressed history), enumerate-and-score actions with a Q-network,
      behavior-clone SmartBot first, then DMC self-play with checkpoint pool.
      Register checkpoints as `rl-<name>` policies in AI_POLICIES.md.
- [ ] SmartBot ideas not yet tried: exhaustion-based void inference (count
      cards, not just observed voids), bury strategy using declared trump
      knowledge, endgame perfect-info solving for the last ~4 tricks.

## Hosting / ops

- [ ] `wss://` + same-origin WebSocket URL (3-line frontend change) — needed
      before any TLS hosting.
- [ ] Dockerfile (build web, install server, run uvicorn) + fly.io single
      instance; alternative: Tailscale for friends-only play with zero deploy.
- [ ] Idle-room sweeper (rooms currently only die when all humans disconnect).
- [ ] Optional: persist in-progress games so a server restart doesn't kill them.

## Polish

- [ ] Portrait-mode phone layout (currently landscape-only with rotate hint).
- [ ] Card-play animations (fly from hand to trick area).
- [ ] Localized UI strings (zh-CN toggle).
