# Backlog

Open work, roughly ordered by value. History of completed items lives in git
and in AI_POLICIES.md; this file tracks what's NEXT.

## AI / training  (current state: mc ~1140 > rl-v6 ~net line ~70 behind — see AI_POLICIES.md)

- [ ] **v7 distillation** (data generating overnight 2026-08-02): N=30
      teacher labels (3x less noise), then v6's recipe (soft targets,
      12 epochs) → gates → Elo pool. The one clean-variable experiment.
- [ ] **AWAC-style policy-head update for self-play** — the designed fix
      for DMC's measured failure (Q-regression collapses any policy
      pathway; two alarm-halted runs). Policy head learns by
      advantage-WEIGHTED imitation; values stay in their own head.
- [ ] **Value-leaf hybrid** (Phase 4's surviving path): truncated rollouts
      + net value head at leaves. Must beat plain mc — note
      net-as-rollout-policy is a measured dead end (55% preview reversed
      to 37%; bare net out-rated its own hybrid).
- [ ] Vectorize bc_train (per-decision loop is MPS-dispatch-bound: 60+
      min/epoch vs ~12 for the ragged-batch trainer).
- [ ] Human-style fine-tune once the human corpus reaches a few thousand
      decisions (currently 227 labeled; grows with every prod game).
- [ ] Measure RISKY_THROWS + TRUMP_BALLOT (MC-vs-MC duels; toggles built
      2026-08-02, need free cores).
- [ ] Next teacher generation inherits CONTROL_LEADS (tonight's N=30 data
      predates it) + record TRACTOR_LOCK decisions as choice-only samples
      (currently absent from all teacher data).
- [ ] From the disagreement miner: dump-selection refinement (n=23, +3.9 —
      humans shed stranded losers/keep trumps better in forced follows);
      lower the CONTROL_LEADS pair gate for late rounds (mid pairs measured
      well). Bot-beats-human follow-discipline categories = coach content.
- [ ] SmartBot ideas untried: exhaustion-based void inference, bury strategy
      using declaration knowledge, exact endgame solving (last ~4 tricks),
      suit-symmetry data augmentation (6x), confidence-weighted CE.
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
