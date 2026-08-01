# Backlog

Open work, roughly ordered by value. History of completed items lives in git
and in AI_POLICIES.md; this file tracks what's NEXT.

## AI / training

- [ ] **MC search distillation** (in progress 2026-08-01): 30k rounds of
      MCBot self-play with per-candidate value targets generating now;
      then the distillation trainer (value regression + choice CE), then
      benchmark vs SmartBot/MCBot + human-agreement tripwire.
- [ ] **Anchored DMC** (recipe v2): warm-start from the distilled net; BC
      ordering anchor (annealed), advantage baseline via V(s) head, forced
      single-candidate decisions filtered from action batches, 30-pair
      in-run evals, team levels added to obs (ENC_VERSION 2). Recipe v1
      post-mortem: RL_PLAN.md.
- [ ] Phase 4 hybrid: MCBot with the net as value function / rollout policy;
      candidate pruning by net priors.
- [ ] Human-style fine-tune once the human corpus reaches a few thousand
      decisions (currently 227 labeled; grows with every prod game).
- [ ] SmartBot ideas untried: exhaustion-based void inference, bury strategy
      using declaration knowledge, exact endgame solving (last ~4 tricks).
- [ ] Inference-weighted world sampling for MCBot (declarer likely long in
      trump, discard-pattern hints).
- [ ] Rules nits from the audit: standard declaration-overcall restrictions;
      throw penalty should force the beaten component, not the global lowest.

## Features

- [ ] **Spectator mode**: watch a room without a seat (read-only state, no
      hand; UI hides the action bar).
- [ ] **LLM commentator / coach** (local Ollama): narrate bot reasoning from
      Memory (voids, boss cards) async; coach mode = compare human play vs
      bot recommendation per trick (the analyze_human pipeline, live).
- [ ] Trick history viewer in the UI (engine records Round.history; xray and
      replay.py exist server-side).
- [ ] Game replay viewer (logs contain full decks; replay.py renders text —
      a UI scrubber would make it shareable).
- [ ] Public lobby list; persistent profiles/stats (needs SQLite); daily
      deal (same seeded shuffle for everyone).

## Hosting / ops

- [ ] GitHub Actions CI: pytest + frontend build on push.
- [ ] Persist in-progress games across server restarts (state is in-memory;
      restart drops games — fine for casual, fix if it ever matters).
- [ ] Decide repo visibility (public-ready per secrets audit; fix commit
      author identity first if desired).
- [ ] True-offline single-player (Pyodide build of the engine) — probably
      not worth it; solo-vs-bots covers the use case.

## Polish

- [ ] Portrait-mode phone layout (landscape-only today, rotate hint shown).
- [ ] Card-play animations (fly from hand to trick area).
- [ ] zh-CN UI strings toggle.
- [ ] X-ray panel: render the per-candidate ±SE the endpoint now returns.
