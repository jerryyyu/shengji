# Backlog

Open work, roughly ordered by value. Completed items live in git and in
AI_POLICIES.md's toggle registry; resolved AI items with their reasoning are
in `docs_archive/backlog-ai-items-through-2026-08-03.md`. This file tracks
what is NEXT — if an item is done, delete it here rather than checking it off.

## AI / training

**The one big question (day 4 close): four separate attempts to give the
search a better evaluator have all produced no measurable strength** — a
better value head (v7w/v9warm/v9scratch indistinguishable, best is oldest),
the flywheel (train on hybrid data → no better hybrid), a learned override on
SmartBot (v10res, 47% vs smart), and a stronger rollout policy (tied twice).
Meanwhile the standalone policy line has resisted five levers and sits at
38-48% vs mc. Before spending more compute on *better evaluators*, the next
work should test what the search is actually limited by.

- [ ] **vleaf follow-up: is it CHEAPER at equal strength?** The settling duel
      answered the strength question — 50.4% at n=1200, a tie (2026-08-03
      23:20). What is still unmeasured is the latency claim: truncating
      rollouts at 4 tricks should cost less per decision, so the open question
      is whether vleaf reaches mc's strength at materially lower wall-clock,
      which would matter for prod responsiveness and for generation
      throughput. Measure decisions/sec at equal N, not round win-rate.
- [ ] **`is_heuristic_baseline` bit** — the model cannot currently see WHICH
      candidate is the heuristic baseline, my top suspect for the standalone
      ceiling. Codex's correction: candidate 0 IS the baseline for valued rows
      but NOT for choice-only TRACTOR_LOCK rows, so mark the recorded `chosen`
      row; zero-init the new input column; assert all three cases in codec
      tests. Then the B+bit arm, same recipe, no simultaneous LR sweep.
- [ ] **Direct V(state) head** — removes 51% of vleaf's per-decision cost
      (enumerate_actions 32% + encode_obs 19%), ~2x generation speed, and is
      the prerequisite for a real PUCT tree. Train toward `max_a` teacher-Q or
      a calibrated bracket distribution, NOT the behaviour return. Gate at
      equal wall-clock.
- [ ] **Representation test** (diagnostic ladder rung 3, the last untested
      ceiling hypothesis besides irreducible ambiguity): add banker's buried
      cards, declaration owner, pair_void, ordered history, team levels;
      needs fresh generation. Rungs 1 and 2 are closed — labels are noisy but
      leave ~19 points of recoverable signal, and the model fits clean labels
      at 99.6%.
- [ ] **Belief net for world sampling** (Libratus/Pluribus-inspired, Jerry
      2026-08-02): predict P(seat holds card | public history), labels free
      from self-play logs, use it to WEIGHT determinizations. This is the one
      remaining net-in-search pathway that does NOT go through the value
      route — and given that four evaluator-quality experiments came back
      null, it is now the more interesting branch. Subsumes pair_void
      sampling and inference-weighted sampling. Gate: weighted vs uniform mc,
      n>=300 seeded.
- [ ] **Sampler point-calibration** — do sampled worlds systematically give
      the feeding seat fewer point cards than reality? A measurable
      distribution question, and the surviving replacement for the withdrawn
      ANTICIPATE_FEED idea.
- [ ] AWAC-style policy-head update for self-play (designed fix for DMC's
      measured failure; advantage-weighted imitation, values in their own
      head). Parked until the questions above resolve.
- [ ] Human-style fine-tune once the human corpus is a few thousand decisions.
- [ ] From the disagreement miner: dump-selection refinement (n=23, +3.9);
      lower the CONTROL_LEADS pair gate for late rounds.
- [ ] SmartBot ideas untried: exhaustion-based void inference, bury strategy
      using declaration knowledge, exact endgame solving (last ~4 tricks),
      suit-symmetry augmentation (6x), confidence-weighted CE.

## Engineering / hardening

- [ ] **Silent-fallback sweep** (asked of Codex 2026-08-03 22:20, awaiting its
      view): every `except: pass`, `return <default>`, and unimplemented
      message path in the decision and protocol layers becomes either a loud
      failure or a documented, tested fallback. Motivation: four defects in
      two days shared this shape — dropped choice-only rows, the banker
      sampler returning candidate 0, `peek_room` unimplemented, `ready`
      missing from in-game state. Each produced plausible output while doing
      nothing.
- [ ] **Codex's remaining frontend cases**: private-hand preservation on seat
      claim; the disconnect/watchdog/reconnect state machine including the
      second-absence reset; chat-before-first-state ordering with >50
      messages; invite precedence with a saved room. (Landed already: peek on
      open/running rooms, peek-then-join-chosen-seat, the two-client seat
      race, ready quorum excluding disconnected humans, `ready` in in-game
      state, seat-claim chat naming the bot.)
- [ ] **P1 hardening from Codex**: per-shard provenance manifests written with
      temp+os.replace (already proved their worth — `teacher_git` cleared
      gen-v4 of the banker bug in one command); FAST_API_VERSION + source
      digest refusing a stale .so; versioned ballot contract asserted at both
      train and play; house-v1 conformance corpus with positive AND negative
      cases.
- [ ] **P1 test coverage**: the failed-throw regression must drive
      `bot_step`/`Room` rather than the engine alone; the npnet parity test
      must use COMMITTED fixtures (it currently passes only because of
      untracked local files).
- [ ] **Scoring-contract fix**: `Game.finish_round()` allows >+3 while
      `round_value()` caps at +3, and `play_game`'s tie fallback awards team 0.
- [ ] Compiled rollout core, remaining phases: leaf ports for
      `_lead`/`_current_winner`/`_cheapest_winning` (~1 day, ~5x), then
      int-native hands (multi-day). Phases 0-2 merged 08-03 at 3.42x.
- [ ] Vectorize bc_train (per-decision loop is MPS-dispatch-bound).
- [ ] Ballot v2 for RL at PLAY time — data side done; never hot-enable under a
      v1-ballot net (Elo 798). Requires teacher generation on v2 first.
- [ ] Rules nits: standard declaration-overcall restrictions; throw penalty
      should force the beaten component, not the global lowest.
- [ ] Xray panel: annotate WHY, not just values; render the per-candidate ±SE
      the endpoint already returns.

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
