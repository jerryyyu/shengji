# Backlog

## EXECUTION VIEW — 2026-08-04 16:57 EDT

One table for "what is happening and what closes it". The detailed reasoning
for each item lives in the sections below, which Codex also maintains — this
view is a summary, not a replacement.

### NOW (running)

No strength experiment is currently validly running. The mini sampler screen
finished, but its artifact does not establish the validity/completeness claims
printed by the script; Air is still listed as running but has not been verified
from this checkout. A sampler/certifier repair is in progress locally.

| item | where | gate that closes it |
|---|---|---|
| **P0 sampler certification repair** | mini code; reconcile Air ledger | On original + late raw reservoir states, independently validate full unseen-card conservation (observer, sampled hands, kitty, played cards), hand sizes, declaration pins, suit voids, pair/tractor obligations, and every individual `None`. Record requested/accepted/rejected counts plus git/tree/config/script/sampler digests. Separately prove completeness on exhaustively enumerable toy states or by a sampler path that can actually consume a planted witness. Distribution fidelity remains a separate later claim. |

### NEXT (highest value first)

| item | why it matters | gate |
|---|---|---|
| **1. Bounded action-semantics gate** | The unsound V3 effective-level equivalence is fixed, but the reported `decompose()` order dependence for tied-level trump pairs remains neither reproduced nor disproved | Exhaustive/metamorphic permutation test over bounded small hands; if it fails, make attempted-play semantics permutation-invariant or represent explicit decomposition |
| **2. Clean 512-state lead-ballot pilot** | The corrected audit finds **51.2% structured lead omission vs 0.9% follows**, almost entirely lead singles. The provisional lead forfeit is larger than follows (2.96 vs 1.01), but selected-max bias means this is directional, not “half provably improvable.” V3 proved widening alone is insufficient | On deal-grouped DEV states balanced across original/late reservoirs, compare current, V3, random-fill, `MC-more`, fixed-14 contextual selection, and full-universe/high-compute using disjoint proposal/report worlds; predeclare fresh-world regret and oracle-best-recall gates |
| **3. CALIB then paired online confirmation** | Offline regret has failed to predict online strength three times | Only the selected ballot arm advances; REPORT stays untouched until selection, then a fixed-size paired evaluator run on fresh seeds must clear arm-minus-MC and arm-minus-control bars with zero protocol failures |
| **4. Clean relabel + learned proposal only after a ballot win** | Repeating 37.1M old-ballot evaluations or training v11pair on actions outside its training ballot cannot improve the champion | Relabel only disagreement/high-uncertainty states under the frozen winning `BallotSpec`; a learned proposer must beat quota, random, and `MC-more` controls before entering production search |

### PRIORITY POLICY

Finish the two bounded correctness gates above, then bias effort roughly
**70% strength / 20% correctness hardening / 10% simplification**. Do not start
a broad cleanup campaign. Simplification moves ahead only when it removes a
duplicate source of experimental truth, makes the next strength test cheaper,
or closes a known silent-failure boundary.

### LATER

Encoder/trainer dataset contract (cleanup #6) · immutable policy specs
replacing the flag matrix (cleanup #4) · `segbatch.py` has no importer while
trainers carry local copies, and `replay_log.pretty_cards` is unreferenced
(cleanup #3) · split the 1,117-line API module along tested seams, only after
the reconnect tests stand as contract tests (cleanup #5) · move
`seatPos`/card helpers out of component modules (cleanup #7) · frontend
concurrent-load soak · exact endgame solving · belief-weighted sampling after
the uniform sampler's distribution fidelity is measured. If learned-prior
racing is ever reopened, first include prior inference in its work/timing
accounting; the current racing claim is closed.

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

**Deterministic evaluation repaired (2026-08-04).** Factory seeds propagate
through the actual runner boundary; constructor failures are not swallowed;
every normal strength claim writes exclusive records/manifests and reports the
paired arm-minus-control contrast. `aggregate_shards.py` refuses duplicate or
unequal records, mixed commits/schemas, and zero-world fallbacks.

**Sampler constraints implemented, certification still open (2026-08-04).**
The greedy allocator was replaced by count-first exhaustive assignment with
forward checking; declaration pins, suit voids and remaining-pair constraints
are consumed, and the post-play tractor inference now correctly records zero
pairs. These are shipped implementation improvements. The independent
certifier is the open P0 because its first artifact checked only a subset of
the advertised invariants and hid five individual `None` returns.

**Action code identity fixed (2026-08-04).** Different card-code multisets no
longer collapse merely because their effective levels tie. The separate
`decompose()` permutation question remains a bounded test item above, not a
reason to keep the known V3 bug open.

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

**Current question (2026-08-04): can a better lead ballot plus correctly
sampled MC beat deployed N=10 MC?** Direct v11pair beats SmartBot but has no
seeded proof over MC; value-leaf, learned root-prior racing, threshold refits,
naive V3 widening, and N=30 scaling all failed to produce a verified edge.
Latency is secondary to strength, so the next experiment tests both fixed-
budget selection quality and a widened high-compute ceiling.

- [ ] **Finish independent sampler certification.** The count-first allocator,
      void/pair constraints and declaration pins are implemented. Repair the
      certifier so it consumes original plus late raw states without rollout-
      generating its own state distribution, checks the complete unseen
      multiset and returned kitty, declaration pins and tractor obligations,
      counts every failed draw rather than only all-draw failures, and records
      immutable provenance. Add exhaustive toy posterior/completeness cases;
      do not call availability across 24 retries “completeness.”
- [ ] **Close the bounded action-semantics gate.** Exhaustively permute small
      tied-level trump hands and compare legality/decomposition/successor state.
      The card-code identity bug is fixed; either reproduce and fix the separate
      list-order problem or close it with a committed property test.
- [ ] **Run the 512-state ballot pilot described in the execution view.** Use
      at most one state per deal, a frozen DEV-only original/late split,
      named independent RNG streams, and per-world/covariance records. Keep
      proposal, oracle-selection, and report worlds disjoint.
- [ ] **Run one paired online confirmation only for the selected ballot arm.**
      Compare against deployed MC and the correct attribution control on fresh
      seeds; enforce exact work counters and all evaluator protocol gates.
- [ ] **Representation or learned-proposal tests only on new-contract labels.**
      If the non-learned ballot wins, compare the current encoder with one
      enriched encoder while holding model/data/init and at least three train
      seeds fixed. Old v11pair cannot score newly widened actions as evidence.
- [ ] **Absolute value contract.** Predict a calibrated attacker scoring-
      bracket distribution or expected signed level utility under one named
      continuation policy. Do not use noisy `max_a Q` as the default target.
      This is a later prerequisite for PUCT/MCTS, not the next champion-path
      experiment and not an implicit extension of v11.
- [ ] **Belief model only after the hard sampler is correct.** Learn card-
      ownership weights from self-play, then compare tempered weighted worlds
      with a validated uniform reference while reporting exact toy-posterior
      calibration and effective sample size. A net must not mask impossible or
      already-biased base worlds.
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
      decision, data-generation, and protocol boundaries. Convert each finding
      into a loud failure or a named, counted, tested fallback. Seed forwarding
      is already repaired; apply this next only around the sampler/certifier and
      then incrementally as strength-path code is touched.
- [ ] **Frontend release soak.** Deterministic coverage is release-candidate
      quality. Before production promotion, run one bounded multi-tab scenario
      covering join, seat race, disconnect-to-bot, reconnect/takeover,
      displaced/stale sockets, second absence, private-hand visibility, chat
      before first state and over 50 messages, and saved-room invite
      precedence. This is a minutes-long ship gate, not an open-ended project.
- [ ] **Remaining provenance and ABI contracts.** Evaluator manifests and
      ballot/checkpoint identities are shipped. Add atomic manifests to data
      generators/certifiers, refuse stale compiled extensions using an API
      version plus source digest, and maintain a house-v1 conformance corpus
      with positive and negative cases.
- [ ] **Boundary-level tests.** Drive the failed-throw regression through
      `bot_step`/`Room` and add a committed high-N raw-record round trip. The
      exact tournament factory-seed boundary and numpy/Torch parity are already
      covered; keep those fixtures green rather than re-queueing their work.
- [ ] **Scoring-contract fix**: `Game.finish_round()` allows >+3 while
      `round_value()` caps at +3, and `play_game`'s tie fallback awards team 0.
- [ ] Compiled rollout core, remaining phases: leaf ports for
      `_lead`/`_current_winner`/`_cheapest_winning` (~1 day, ~5x), then
      int-native hands (multi-day). Phases 0-2 merged 08-03 at 3.42x.
- [ ] Vectorize bc_train (per-decision loop is MPS-dispatch-bound).
- [ ] Unify MC/data/RL generation behind the selected executable `BallotSpec`
      before training a proposal model. Never hot-enable a widened play ballot
      under an old-ballot net (the Elo-798 failure).
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
