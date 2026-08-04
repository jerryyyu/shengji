# Backlog

## EXECUTION VIEW — 2026-08-04 17:30

One table for "what is happening and what closes it". The detailed reasoning
for each item lives in the sections below, which Codex also maintains — this
view is a summary, not a replacement.

### NOW (running)

Nothing running. The determinization screen closed negative and the late-ply
capture finished (12,000 states, pulled to `rl_data/highn_late_air.jsonl`).

| item | where | gate that closes it |
|---|---|---|

### NEXT (highest value first)

| item | why it matters | gate |
|---|---|---|
| **2. Action-identity P0** | "one representative per effective level" is not a sound equivalence, and `decompose()` keeps input-order dependence for tied-level trump pairs while dedupe uses a sorted multiset — generator and engine can disagree about which action was played | permutation-invariant attempted-play semantics, or an explicit decomposition choice |
| **3. BALLOT_PLAN arm one** — evaluation-free archetype quotas | Leads carry **3x** the forfeit of follows (2.96 vs 1.01 points), half are provably improvable, and the ballot omits **54.0% of the structured lead space vs 0.9% of follows** (dev-split audit, 12,340 states). BUT coverage is known NOT to be sufficient on its own — V3 added exactly the missing singles and did not confirm. This arm must win on SELECTION quality at a fixed budget | `MC-more` in the same comparison; paired and controlled |
| **5. `pair_void` has no sampler consumer** | computed and never used; Codex has raised it three times and it gates any final sampler claim | sampler refuses to deal a pair into a proven pair-void seat |
| **6. Clean-contract high-N relabelling** — capture states first, relabel only the stratified union we will report | avoids repeating 37.1M old-ballot evaluations; the only route to labels worth training on | new schema; report worlds never used for selection |

### LATER

Encoder/trainer dataset contract (cleanup #6) · immutable policy specs
replacing the flag matrix (cleanup #4) · `segbatch.py` has no importer while
trainers carry local copies, and `replay_log.pretty_cards` is unreferenced
(cleanup #3) · split the 1,117-line API module along tested seams, only after
the reconnect tests stand as contract tests (cleanup #5) · `MCPriorRace` has no
inference timer and `MCBot.search_secs` starts after the prior runs, so every
"equal compute" claim is incomplete · move `seatPos`/card helpers out of
component modules (cleanup #7) · frontend concurrent-load soak · belief-weighted
sampling (the sampler is the one direction never tried).

### CLOSED — do not re-queue

**Ballot identity enforced (2026-08-04).** `BallotSpec` derives identity from
the live value of all nine attributes `_candidates()` reads plus a digest of
the generator's source AND the compiled `_fast` binary it calls. Checkpoints
carry provenance sidecars; unstamped fails closed. Policies that run no search
report `none@v0` instead of a fabricated MC identity. 16 tests.

**Late-ply supplement captured (2026-08-04).** 12,000 states, ply 15-57. Takes
ply>=20 coverage from 844 to 9,237 states (10.9x), which is the distribution
gap that mis-aimed v13. Raw states only — its N=240 labels are contract-dirty.

**Evaluator consolidated (2026-08-04).** The protocol now lives in
`shengji/evaluation.py` with `scripts/evaluate.py` as a thin CLI. Deleted:
`race_confirm`, `vleaf_settle`, `gate_duel`, `kitty_duel`, `v11_extend`,
`pool_20260804` — 35 scripts down to 31. Their seed/interval invariants are
guarded by `tests/test_evaluation_lib.py` (10 tests). `t3_gate_screen.py`
was NOT retired: it is a screen with its own logic, not another duel runner.

vleaf equals mc · vleaf with a pairwise head is INVALID not merely failed ·
v10res was a no-op checkpoint · root-prior racing refuted by its own control ·
V3 lead ballot NOT CONFIRMED · direct-V leaf v13abs NOT CONFIRMED (doubly
misaligned) · margin 0.005 NOT CONFIRMED · BANKER_KITTY correctness-only ·
absolute value heads interchangeable · heuristics #2/#4 · ANTICIPATE_FEED ·
mc-smartroll · standalone policy line PAUSED as a development target.

**Standing rules.** Strength claims go through `scripts/evaluate.py` and no
other path. Six claims have died to correlated blocks read as reproduction: a
screen may reject, only a paired confirmation may promote. Offline regret on
the high-N corpus has failed to predict online strength three times — it may
reject, never promote.

---

## Detail (maintained with Codex)

Open work, roughly ordered by value. Completed items live in git and in
AI_POLICIES.md's toggle registry; resolved AI items with their reasoning are
in `docs_archive/backlog-ai-items-through-2026-08-03.md`. This file tracks
what is NEXT — if an item is done, delete it here rather than checking it off.

## AI / training

**Current question (2026-08-04): can v11pair's relative root ranking allocate
a fixed MC budget better than plain MC, direct v11, and cheap allocation
rules?** Direct v11 convincingly beats SmartBot and is plausibly near MC at a
small fraction of its latency, but the MC comparison is only an unseeded
screen. The selective-search runner and current high-N builder are not valid
measurement instruments. The next work is correctness and measurement, not a
larger experiment.

- [ ] **Make belief sampling constraint-correct.** Enforce every proven suit
      void, pair-void constraint, and declared-card pin on every sampled world.
      Strict mode now rejects/counts the last-retry suit-void relaxation;
      normal mode may still use it and pair-voids remain unenforced. Expose
      requested/valid/rejected/relaxed counts for all seats and add impossible-
      state, pair-void, and last-retry regressions before generating labels.
- [ ] **Repair deterministic evaluation.** Replace
      `tournament._seeded()`'s no-`rng` fallthrough with an unconditional
      return, test both a seedless deterministic bot and a constructor that
      raises internally through that exact boundary, and persist/compare every
      deal-seed and flip result. Every run needs an exclusive output plus
      immutable manifest and checkpoint hash.
- [ ] **Settle the deployment Pareto choice.** On the repaired evaluator,
      compare SmartBot, direct v11pair, MC N=5/10/20, and the settled v7 value-
      leaf speed arm. Predeclare signed level utility as primary, the
      non-inferiority/superiority margin, seed clusters, and latency method.
      The existing 4,880-round v11-vs-MC aggregate is SCREEN evidence, not a
      confirmation.
- [ ] **Build a valid, tiny high-N diagnostic pilot.** Before running the
      prototype again—or using the completed Air artifact as evidence—add a
      versioned raw-state round trip (including initial banker and declaration
      history), strict worlds, deal-grouped
      splits, phase/score quotas, disjoint candidate-selection and evaluation
      worlds, stored per-world differences/covariance, collision-free named RNG
      streams, a cost estimate, and exclusive manifested output. Inspect the
      pilot before authorising a corpus.
- [ ] **Representation test on independent labels.** Compare the current
      encoder with exactly one enriched encoder on that frozen pilot, holding
      model, initialization, data, and at least three train seeds fixed. Test
      trump-relative canonicalisation, ordered recent tricks, declaration
      owner/cards, pair-voids, team levels, and legal banker-private burial.
      Bulk generation is earned only by consistent untouched-regret gains.
- [ ] **Root racing, not v11 leaf evaluation.** Give every legal root action a
      common-world rollout floor, then allocate the remaining fixed budget
      using v11 rank plus empirical uncertainty. Compare with uniform and
      candidate-count allocation at equal actual rollouts or policy-local
      wall time. v11pair's scale is relative within a state and is invalid as
      an MC/MCTS leaf value.
- [ ] **Absolute value contract.** Predict a calibrated attacker scoring-
      bracket distribution or expected signed level utility under one named
      continuation policy. Do not use noisy `max_a Q` as the default target.
      This is a prerequisite for PUCT/MCTS, not an implicit extension of v11.
- [ ] **Belief model only after the hard sampler is correct.** Learn card-
      ownership weights from self-play, then compare tempered weighted worlds
      with uniform worlds while reporting effective sample size and sampler
      calibration. A net must not mask impossible base worlds.
- [ ] **AWAC-style self-play is parked, not disproven.** Resume only after
      role-sign, immutable-artifact, evaluator, and fallback invariants are
      tested. Start with a bounded shadow run and keep policy advantages out
      of the absolute value head.
- [ ] Human-style fine-tune once the human corpus is a few thousand decisions.
- [ ] From the disagreement miner: dump-selection refinement (n=23, +3.9);
      lower the CONTROL_LEADS pair gate for late rounds.
- [ ] SmartBot ideas untried: exhaustion-based void inference, declaration-
      aware burying, exact endgame solving (last ~4 tricks), suit-symmetry
      augmentation, and confidence-weighted CE.

## Engineering / hardening

- [ ] **Bounded silent-fallback sweep.** Inventory broad catches, default
      actions, constraint relaxation, and unimplemented protocol paths in the
      decision/evaluation/protocol boundaries. Convert each finding into a
      loud failure or a named, counted, tested fallback. This directly covers
      the current sampler and `_seeded()` holes; keep enforcing the rule as
      touched code evolves.
- [ ] **Frontend release soak.** Deterministic coverage is release-candidate
      quality. Before production promotion, run one bounded multi-tab scenario
      covering join, seat race, disconnect-to-bot, reconnect/takeover,
      displaced/stale sockets, second absence, private-hand visibility, chat
      before first state and over 50 messages, and saved-room invite
      precedence. This is a minutes-long ship gate, not an open-ended project.
- [ ] **Provenance and ABI contracts.** Write per-shard manifests with
      temp+`os.replace`; refuse stale compiled extensions using an API version
      plus source digest; assert the versioned ballot contract at collection,
      training, and play; maintain a house-v1 conformance corpus with positive
      and negative cases.
- [ ] **Boundary-level tests.** Drive the failed-throw regression through
      `bot_step`/`Room`, test the exact tournament seed boundary, round-trip a
      high-N raw record, and keep numpy/Torch parity on committed fixtures.
- [ ] **Scoring-contract fix**: `Game.finish_round()` allows >+3 while
      `round_value()` caps at +3, and `play_game`'s tie fallback awards team 0.
- [ ] Compiled rollout core, remaining phases: leaf ports for
      `_lead`/`_current_winner`/`_cheapest_winning` (~1 day, ~5x), then
      int-native hands (multi-day). Phases 0-2 merged 08-03 at 3.42x.
- [ ] Vectorize bc_train (per-decision loop is MPS-dispatch-bound).
- [ ] Ballot v2 for RL at PLAY time — data side done; never hot-enable under a
      v1-ballot net (Elo 798). Requires teacher generation on v2 first.
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
