# Backlog

Open work, roughly ordered by value. History of completed items lives in git
and in AI_POLICIES.md; this file tracks what's NEXT.

## AI / training

**Top of the list after day 4 (2026-08-03):**
- [x] ~~warm vs scratch~~ **ANSWERED: no difference** (48%/39% vs
      48%/38%, seeded anchors, identical data). Warm neither traps nor
      helps. Both arms peaked at their LAST snapshot => both
      undertrained; the epochs question is open and now testable under
      the seeded protocol.
- [ ] **Extend the undertrained arms**: v9warm/v9scratch to 12-16
      epochs, re-battery under seeded anchors. Cheap (~5 min/arm). This
      is the one recipe lever not yet cleanly tested.
- [ ] **The standalone-policy ceiling is the real problem.** Five levers
      tried, none moved it: more data, better-than-search labels
      (gen-v4), more epochs, corrected target (margin-aware), warm-vs-
      scratch. Nets sit at 38-48% vs mc regardless. Candidates for the
      actual constraint, in order of my confidence:
      (a) the independent-candidate scoring architecture — the model
          cannot see WHICH candidate is the heuristic baseline
          (`is_heuristic_baseline` bit, still unbuilt);
      (b) the encoding (531-dim; no trump-relative canonicalisation —
          ShengJi+ reported better point differentials with it);
      (c) the absence of ANY lookahead at play time, which is exactly
          what the vleaf result suggests matters most.
- [ ] **Direct V(state) head** — biggest perf AND capability item:
      removes per-leaf enumerate_actions (32%) + encode_obs (19%),
      ~2x generation and vleaf latency, and is a prerequisite for a
      real PUCT tree.
  (current state: mc ~1140 > rl-v6 ~net line ~70 behind — see AI_POLICIES.md)

- [x] v7/v7-warm DONE 2026-08-02: warm-from-v6 on N=30 beat v6 in all
      4 snapshots (best ep02 64.5% n=200); warm-start = standing policy;
      scratch killed. NEXT: **v8 = warm from v7w-ep02 on gen-v3** (data
      generating overnight on both machines); lead-weighted loss arm
      still available as a v8 variant.
- [ ] **WARM vs SCRATCH — the untested control (Jerry, 2026-08-03).**
      Hypothesis: warm-starting each generation from the previous net traps
      us in an inherited basin, so better data only fine-tunes an old
      teacher's style. Evidence: v7w (warm from v6) gained +1..+5; v8a/b/
      along (warm from v7w) ALL landed below v7w on 2.2x better data; the
      net line has sat at 1040-1060 Elo for five generations while the
      teacher climbed 40. We never actually ran the control — v7-scratch
      was killed at epoch 1/8 for being slow, and "warm wins" was inferred
      from speed, not a completed comparison.
      EXPERIMENT (on gen-v4, when spare capacity exists — do NOT displace
      the main line): train v9-warm (from snapshots_v7w/ep02.pt, lr 3e-4)
      and v9-scratch (random init, lr 1e-3) on identical data, per-epoch
      snapshots, anchors-first battery on both. Cost is now trivial:
      scratch training fell from 8h/epoch to ~2.5 min/epoch after the
      Cython work. If scratch >= warm, warm-start stops being standing
      policy and every future generation gets both arms.
      Related learning levers behind it: LR schedule (fixed today), the
      independent-candidate scoring architecture (Codex flagged that row
      identity is invisible to the model), lead/follow loss weighting
      (75% of rows are follows).
- [ ] **AWAC-style policy-head update for self-play** — the designed fix
      for DMC's measured failure (Q-regression collapses any policy
      pathway; two alarm-halted runs). Policy head learns by
      advantage-WEIGHTED imitation; values stay in their own head.
- [ ] **Value-leaf hybrid**: v1 (v6 head) FAILED gate 45% (n=120);
      retry WITH v7w head running 2026-08-02 night. Original design: truncated rollouts
      + net value head at leaves. Must beat plain mc — note
      net-as-rollout-policy is a measured dead end (55% preview reversed
      to 37%; bare net out-rated its own hybrid).
- [~] **Compiled rollout core** — phases 0-2 MERGED 08-03 (**3.42x**,
      55/55 both modes, goldens identical; opt-in SHENGJI_FAST=1; deep
      generation-value validation in flight before gen/duels switch).
      Remaining: leaf ports for _lead/_current_winner/_cheapest_winning
      (~1 day, ~5x), then int-native hands (multi-day). Original notes:
      profiled
      2026-08-02: ~99% of MC time is the rollout loop (per round: 181k
      heuristic decide_play, 845k decompose, 282k beats, 278k
      validate_follow — all str/dict Python). Plan: (1) int-encode cards
      (u8) + array hands inside engine primitives — this restructure is
      most of the win and is required for either language; (2) Cython
      pass over combos/legal/heuristic hot loop (~days, est 10-20x,
      incremental, same repo); (3) Rust/PyO3 full engine core ONLY if
      AWAC-scale demands 100x (bonus: wasm build = true-offline client;
      risk: two rule implementations drifting — Python engine becomes
      the differential-test oracle, parity on 10k seeded rounds
      mandatory before any generated data is trusted).
- [ ] Vectorize bc_train (per-decision loop is MPS-dispatch-bound: 60+
      min/epoch vs ~12 for the ragged-batch trainer).
- [ ] Human-style fine-tune once the human corpus reaches a few thousand
      decisions (currently 227 labeled; grows with every prod game).
- [x] RISKY_THROWS / TRUMP_BALLOT measured at MC level: 53%/53% ties
      (combined test optional); MC stack validation 57% — inheritance
      assumption confirmed.
- [ ] Next teacher generation inherits CONTROL_LEADS (tonight's N=30 data
      predates it) + record TRACTOR_LOCK decisions as choice-only samples
      (currently absent from all teacher data).
- [x] ~~ANTICIPATE_FEED~~ **WITHDRAWN 2026-08-03 — the premise was false.**
      Probed the rollout policy directly: it feeds points onto a partner's
      winning ruff in **38/38 opportunities (100%)** (`strong = inc_suit ==
      TRUMP` sets prefer_points). The RTLT diagnosis ("rollouts don't model
      the feed") was wrong; the search valued the duck at 70.2 vs 71.6/71.8
      for over-ruffs WITH feeding modelled, i.e. it made a correct
      expected-value choice that lost to realization (Sk happened to hold
      two 10s). The ledger claim that 3 "lapses" cost 45 points is
      likely wrong for the over-ruff cases. REPLACEMENT candidate worth
      measuring: **sampler point-calibration** — do sampled worlds give the
      feeding seat systematically fewer point cards than reality? That is a
      measurable distribution question, not a policy fix.

- [ ] From the disagreement miner: dump-selection refinement (n=23, +3.9 —
      humans shed stranded losers/keep trumps better in forced follows);
      lower the CONTROL_LEADS pair gate for late rounds (mid pairs measured
      well). Bot-beats-human follow-discipline categories = coach content.
- [ ] SmartBot ideas untried: exhaustion-based void inference, bury strategy
      using declaration knowledge, exact endgame solving (last ~4 tricks),
      suit-symmetry data augmentation (6x), confidence-weighted CE.
- [ ] Pair-void-constrained world sampling for MCBot: Memory.pair_void
      (2026-08-02) proves seats hold no pair in a suit — never deal them
      one in sampled worlds. Makes rollout pricing of pair/throw leads
      accurate; feeds WIDE_LEAD_BALLOT. (The heuristic-gate use tied at
      n=400; the sampler use is the sharper one.)
- [ ] Ballot v2 for RL — data side DONE 2026-08-02 (throws + component
      combos in rl/actions.py; human-play coverage 99.3%, tripwire:
      scripts/audit_sourcing.py; human_v2 shards rebuilt with it). Still
      to do: teacher generation on v2 ballots → train → only then flip
      play-time (never hot-enable under a v1-ballot net — Elo 798).
- [ ] Xray panel: annotate WHY, not just values — e.g. "throw unbeatable:
      no trump pair for the AA component" (JVRA confusion, 2026-08-02).
- [ ] **Belief net for world sampling** (Libratus/Pluribus-inspired,
      Jerry 2026-08-02): small net predicting P(seat holds card | public
      history) — labels free from self-play logs (hidden hands recorded).
      Use to WEIGHT MC determinizations instead of uniform sampling;
      subsumes inference-weighted sampling (declarer long in trump) and
      generalizes pair_void's hard proofs to soft evidence. Gate:
      weighted-sampling mc vs uniform mc, n=120. Third net-in-search
      pathway that avoids the fragile value route entirely.
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
