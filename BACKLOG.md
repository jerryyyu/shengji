# Backlog

## EXECUTION VIEW — 2026-08-05 09:00 EDT

One table for "what is happening and what closes it". The detailed reasoning
for each item lives in the sections below, which Codex also maintains — this
view is a summary, not a replacement.

### NOW

Both code gates are CLOSED (2026-08-05). The freezer enforces the registered
size and role marginals, size now drives deal selection, and a shortage or
replay error publishes nothing; the runner requires an explicit artifact plus
its sha256 (compared before parsing), refuses any experimental sampler flag,
and labels limited runs `smoke` so they cannot pool into a DEV verdict. v4 is
frozen from clean `4d0f1d3` — DEV `1cab080956d038b3`, CALIB `8c55b3f809d43992`
— and all 1,024 rows replay.

**The only thing left before launch is Codex answering PASS on the gate packet
in `HANDOFF_ACTIVE.md`.** Pilot scoring is 0/512 and the 8-shard command is
written but deliberately not run. Nothing here is self-certified.

The sampler remains posterior-incorrect and all repair flags remain OFF. That
is a separate P1 correctness lane. DEV is allowed to compare ballot/search
designs under the frozen sampler actually used in production; CALIB and online
games are still required before any strength or deployment claim.

### Plain-English strength path

Think of the sequence as **build the exam -> try ideas -> verify the winner ->
play real games -> teach a model from clean answers**:

| item | plain English | status / exit condition |
|---|---|---|
| **0. Freeze the exam** | Create two balanced lists of real lead decisions. DEV is the worksheet; CALIB is the unopened exam. No model trains on either. | **Built and audited, awaiting Codex sign-off.** v4 frozen from clean `4d0f1d3`: exact size/role quotas, size drives selection, publication fails closed, 1,024 rows replay, DEV/CALIB deal-disjoint. Not self-certified. |
| **1. Try ballot designs on DEV** | On the same 512 situations, ask whether smart candidate selection beats the current ballot, random extra candidates, simply spending more MC on the old ballot, and brute-force widening. | **Ready, blocked on the gate packet only.** Runner pins the artifact hash and refuses flagged/short/smoke launches; 8-shard command is written. Scores under the sampler production deploys — a strength screen, not a posterior-correctness claim. |
| **2. Verify once on CALIB** | Take the single DEV winner, lock every setting, and run it on 512 situations it never saw. This catches an idea that merely fit DEV. | **Waiting on item 1.** No tuning or second candidate after seeing CALIB. |
| **3. Play real paired games** | Put the frozen candidate and current production MC into full games built from the same deal seeds and seat flips. This answers “does it actually win Shengji?”, not merely “does it score actions better offline?” | **Waiting on CALIB.** Must improve paired signed level utility against current MC, while a null control stays flat and every protocol counter is clean. |
| **4. Learn from the winner** | Only after a ballot truly wins, regenerate labels for the new action space and train a model to propose/rank those actions cheaply and consistently. | **Waiting on an online win.** The learned proposer must beat simple quota, random-fill, and more-MC controls before entering production search. |

### NEXT (highest value first)

| item | why it matters | gate |
|---|---|---|
| **0. Finish the 512-state freeze** | Current v3 bytes pass a full replay/count/disjointness audit, but the mechanism can still publish a short/error-bearing set and candidate size is only a within-deal tie-break | Enforce the exact common band-size and role marginals in `HANDOFF_ACTIVE.md`, make every mismatch fail before publication, exercise those failures in tests, then freeze new-salt v4 DEV/CALIB artifacts from clean code and independently validate all 1,024 rows |
| **1. DEV-512 lead-ballot selection pilot** | The refreshed audit found **51.2% structured lead omission vs 0.9% follows**, almost entirely lead singles. The provisional lead forfeit was larger than follows (2.96 vs 1.01), but selected-max bias makes it directional, not “half provably improvable.” V3 proved widening alone is insufficient | Compare current, V3, random-fill, `MC-more`, fixed-14 contextual selection, and full-universe/high-compute using disjoint proposal/report worlds. Predeclare fresh-world regret, oracle-best-recall and work gates; select exactly one design or select none |
| **2. One frozen design on untouched CALIB-512** | Offline regret has failed to predict online strength three times, so DEV selection cannot promote its own winner | Freeze the full `BallotSpec`, selector/quota, rollout allocation and thresholds before CALIB. Run the chosen design once; no post-CALIB tuning, arm substitution or pooling back into DEV. REPORT remains untouched by selection |
| **3. Paired online strength confirmation** | A ballot can improve fixed-state regret without improving the game | On fresh deal seeds, the frozen candidate must clear arm-minus-current-MC and arm-minus-null/control bars in paired signed level utility with zero protocol failures; full-game level progression is the final deployment check. Any one-shot REPORT audit must be preregistered and cannot tune the design |
| **4. Clean relabel + learned proposal only after a ballot win** | Repeating 37.1M old-ballot evaluations or training v11pair on actions outside its training ballot cannot improve the champion | Relabel only disagreement/high-uncertainty/late states under the frozen winning `BallotSpec`; train a lead-specific proposer, and require it to beat quota, random and `MC-more` controls before it enters production search |

### POST-512 CONTRACT

“512 states” names a **frozen evaluation artifact**, not a supervised or RL
training dataset. The post-freeze sequence is therefore:

1. score all registered arms on DEV-512 with independent proposal/report
   worlds and clustered paired uncertainty;
2. select exactly one complete design on DEV (or stop with no winner), then
   freeze its ballot, selector, allocation and thresholds;
3. run that one design once on disjoint CALIB-512 without tuning;
4. only a CALIB pass earns fresh-seed paired online confirmation against
   current MC and a null/control; REPORT is never used to choose or repair the
   arm;
5. only an online win earns targeted relabelling and learned-proposer training.

An N=60-versus-N=30 current-main dose test is an **orthogonal lane**, not a use
of the 512 states and not permission to change the pilot's registered work
budgets. Use fresh paired deal seeds, an independent N=30 null, strict sampling
and one fixed block with no extension. If both a higher-N policy and a new
ballot win independently, their combination needs one final direct
confirmation because ballot width and determinization dose can interact.

### PRIORITY POLICY

Run the refreshed lead audit and clean 512-state pilot, then bias effort roughly
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

**Sampler P0 validity/support certification passed (2026-08-04, `eea78d2`).**
The greedy allocator was replaced by count-first exhaustive assignment with
forward checking; declaration pins, suit voids and remaining-pair/run
constraints are consumed. A clean artifact checked 1,600 original+late
reservoir states (38,399 accepted worlds, one counted rejection, zero invalid)
and reached every legal world plus the real-deal witness in 120/120 exhaustively
enumerated toy states. This closes P0, not posterior fidelity.

**Rewritten-sampler N=30 confirmed (2026-08-04).** On 504 preregistered fresh
clusters, N=30 minus N=10 was `+0.262 +/- 0.154`; N=30 minus the true null was
`+0.310 +/- 0.153`, while null minus N=10 was `-0.048 +/- 0.162`. This closes
the dose question on the evaluated pre-action-fix revision; it does not prove
an RL edge or posterior fidelity.

**Bounded submitted-action semantics verified (2026-08-04).** Different card-
code multisets no longer collapse merely because their effective levels tie,
and `decompose()` now canonicalises its input in pure and compiled kernels.
The six-card `C7 C7 D7 D7 H7 H7` witness, 30,936 bounded reorderings, cold and
warm caches, and the real failed-throw `Round.play` successor are invariant.
`find_tractor_runs()` now enumerates every physical tied-code choice in both
kernels; the live MC ballot contains both successor-distinct tractors under
either hand ordering, and anagrams enumerate identically. The product is
bounded at three choices in suited trump and four in no-trump; a deterministic
20,000-hand scan found an added run in 11 hands (0.055%), with no explosion.
Both full suites pass (176 passed, 2 skipped per engine). Sorting is sound for
all arities by construction, and both memos are per-`Ordering`. The tractor
memo deliberately retains its cheaper exact-order key: canonical sorting was
3x the key-construction cost on this 815k-call/round hot path, while values are
still canonical.

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

**Current question (2026-08-04): can a better lead ballot beat verified N=30
MC?** The preregistered rewritten-sampler confirmation established N=30 over
N=10 at `+0.262 +/- 0.154` on 504 fresh clusters with a flat null control.
Direct v11pair beats SmartBot but has no seeded proof over MC; value-leaf,
learned root-prior racing, threshold refits, and naive V3 widening all failed
to produce a verified edge. Latency is secondary to strength, so the next
experiment is fixed-budget versus widened/high-compute ballot selection.

- [ ] **Measure and repair sampler posterior fidelity (P1).** Enumerate exact
      legal toy posteriors, then compare total-variation distance, per-card/seat
      marginals and exchangeability. Weight count matrices by their number of
      admissible concrete fills and replace greedy capped-card placement with a
      uniform constrained draw. Also make reservoir reconstruction replay the
      stored declarations directly; all 1,600 P0 rows matched today, but that
      should be structural rather than dependent on current bot behavior.
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
- [ ] **Repair the DMC2 contract before any AWAC/DMC resume.** The oracle is
      attacker-perspective, but dmc2 negates defender returns without negating
      the oracle before subtraction; add an attacker/defender antisymmetry test
      and fix the target. Stop calling the scalar residual “Suphx oracle
      guiding”; separately micro-test (a) Suphx-style privileged-policy feature
      removal and (b) DouZero-style from-scratch role-conditioned direct Q.
      Actors must load immutable snapshots and the gate must use the clustered
      evaluator. Start synchronously for 20-30 minutes; only stable spread plus
      a predeclared held-out improvement earns a fleet run.
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
- [ ] **One immutable `ExperimentSpec` and bounded fleet queue (AutoGo lesson).**
      Unify hypothesis, code/data/ballot/encoder hashes, frozen actor paths,
      seeds, budget, primary metric, null, stop rule and artifact destinations.
      First make collect→train→evaluate exactly replayable synchronously; only
      then let a dispatcher keep both machines full from preregistered jobs.
      Scheduling may be automatic; promotion and metric changes may not be.
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
