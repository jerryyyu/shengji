# RL Plan: training a learned Sheng Ji policy

Goal: a neural policy that **beats MCBot in the Elo tournament pool**
(the standing "Elo > 1137" milestone — pool-relative, so operationally:
rl above mc in the same pool). Hardware: one Mac mini (M4, 10 cores,
MPS). Everything measured: mirrored deals, fixed-seed probes, direct
duels, Elo pools, human-agreement tripwire. Toggle-level results live in
AI_POLICIES.md; run archives in `server/runs/`.

---

## STATE OF PLAY (2026-08-03 morning, day 4)

**Prod**: mc with BOTH wide ballots (leads 62%, follows 60% over its
predecessor), pool 1109, deployed 08-02 evening. NOT yet deployed:
DECLARER_PIN + the lowest-beatable throw-penalty rule + correctness
fixes — all in main, awaiting Jerry's next deploy.

**Best net: rl-v7w** (`snapshots_v7w/ep02.pt`) — warm from v6, 4 epochs
on the N=30 textbook (~1.5h). Controlled same-seed anchors vs v6: ahead
on all four (45/43 smart, 41/36 wide-mc, 52/48 smart-0801, 43/42
smart-v2) — a modest, real, transitive +1..+5. Warm-start from the
incumbent is standing policy (~5x iteration speed).

**gen-v3 (running, ~52%)**: the first textbook written by the 1109
teacher — N=30, wide ballots, v2 throws, TRACTOR_LOCK choice samples,
META provenance. Mini ~14.6k rounds banked (24 shards); Air ~6.5k (7
shards) + phase-2 on a reduced 6k budget; mini absorbs the rebalance
(~13k more) since its unniced workers run ~3-5x the Air's niced rate.
PROVENANCE (verified 08-03 maintenance): the Air ran phase-1 on the
ORIGINAL engine until 08:15 (7 shards / 6.5k rounds — no DECLARER_PIN,
old throw-penalty rule); its phase-2 (ids 300-306) and the mini
phase-2/3 shards carry both fixes. Mixed-generation data is acceptable
(same rules, better-informed later sampling) but v8 post-mortems should
know the split. Mid-run engine upgrades mean later shards are
strictly better-informed; 2 shards from the buggy-memo
window are QUARANTINED (`rl_data/gen_v3_quarantine/`, excluded from
training).

**Engine speed: Cython phases 0-2 merged** — 3.42x per MC round
(5.74s -> 1.68s), 55/55 tests in BOTH modes, goldens byte-identical
across 6 seeds. Opt-in only (`SHENGJI_FAST=1`); a deep validation pass
(generation-VALUE parity, 300-round sweep, duel equivalence) gates
whether generation and duels switch over.

**Correctness**: suite 34 -> 55 tests overnight. Two audit-found bugs
fixed (cache-key/computation mismatch; live cache alias in the throw
penalty), plus hash-order determinism repairs. The golden-history guard
caught two of its own regressions on day one. See CORRECTNESS.md.

**From RTLT (Jerry's session, xray-verified)**: DECLARER_PIN flips the
K-pair-into-declared-pair blunder at the exact position (HK-HK went
from best-on-ballot to second-worst); the ducked over-ruff root cause
is that rollout policies don't model a partner FEEDING points to the
winner (ANTICIPATE_FEED WITHDRAWN 2026-08-03: probe shows rollouts DO feed
(38/38); the search preferred the duck WITH feeding modelled, so those
plays were expected-value-correct and lost to variance, not lapses). Human corpus now 1,592 decisions (+59%).

## ✅ VLEAF ADOPTED (2026-08-03 16:00) — three blocks + pool

| block | seeds | result |
|---|---|---|
| 1 | 0 | 72-48 (60%) |
| 2 | 777 | 72-48 (60%) |
| 3 | 31337 | 73-47 (61%) |
| **combined** | | **217-143 = 60.3% at n=360** |

95% CI ~[55.2%, 65.4%] — lower bound CLEARS the 55% bar, so adopted by
our own rules. Pool: `mc-vleaf-v7w-ep02` **Elo 1163** vs mc 1110.
Block 4 still running (tightens further, cannot overturn).

**Also settled today**: SIZE_FIRST at MC level 52% (tie at both levels —
rejected); A-long 12 epochs = 38% vs mc vs arm A's 34% at 4 epochs, a
4-point gap INSIDE the +-6-7% noise floor => more epochs had NO effect;
vleaf with v8a's value head tracked ~54% vs v7w's 60-61%, so gen-v3
produced a worse EVALUATOR as well as a worse player — v7w-ep02 stays
the value head of record.

**PRODUCTIONIZED**: numpy inference path (`rl/npnet.py`) mirrors the net
in ~40 lines; verified identical play history vs torch and 200-case
argmax parity; 14ms/decision (FASTER than torch's 17ms, equal to plain
mc). Prod image needs NO torch — just numpy + 2MB weights. Deploy with
`SHENGJI_BOT=mc-vleaf-v7w-ep02` on Jerry's go.

## Superseded: pool table (2026-08-03 15:00)

**`mc-vleaf-v7w-ep02` = Elo 1163** vs mc 1110, smart 1089, rl-v7w 1060,
rl-v8a 1047, heuristic 1000 (6-entrant pool, same seeds, round-level).
Head-to-head: beat mc 70-50, smart 74-46, heuristic 84-36. Plus duel
blocks 1 (60%) and 3 (61%) on independent seeds — four seed sets agree.

**NAMING**: always name the hybrid by its VALUE HEAD
(`mc-vleaf-<net>-<epoch>`); the hybrid's strength is the head's. Both
variants are registered (`mc-vleaf-v7w-ep02`, `mc-vleaf-v8a-ep03`) so
the result is repo-reproducible — Codex correctly flagged that the
first headline was not.

**What it does and does not mean**: for the first time a configuration
containing the net is the strongest thing we have — but the net is
EVALUATING inside the search, not playing. Standalone nets remain
50-60 Elo below mc. The project goal ("an RL policy above mc") is met
on a plain reading, but the honest framing is: *the search got stronger
by borrowing the net's judgment*. Pure-policy parity is still unmet.

**Unlocks**: (1) a teacher ABOVE the distillation ceiling — gen-v4
recorded from the hybrid would be the first dataset whose labels beat
mc; (2) a deployable bot (17ms vs 14ms/decision — the blocker is that
prod has never shipped torch, not speed).

## Superseded: second-block confirmation (2026-08-03 14:00)

**Block 1** (seeds 0, pure engine): vleaf(v7w) 72-48 vs mc = **60%**
**Block 3** (seeds 31337, fast engine, fresh): 73-47 = **61%**
**Combined: 145-95 = 60.4% at n=240**, two independent seed sets.

95% CI ~[54.2%, 66.6%] — the lower bound sits ON our 55% adoption bar,
so this is a strong screen, NOT yet an adoption. Blocks 2 (pure, ~4h,
still running) and 4 (Air, fresh seeds) will take it to n~480 and
decide. Per Codex: judge on the paired level-utility interval, not two
point estimates.

**If it holds, this is the flywheel**: a search+net hybrid stronger than
plain mc is a teacher above the distillation ceiling — gen-v4 records
vleaf instead of mc, and the next student learns from above-mc play for
the first time. NO adoption or deploy without Jerry.

## Superseded pending block (2026-08-03 ~02:30)

**vleaf(v7w-ep02 value head, 4-trick truncation) beat wide-ballot mc
72-48 (60%, n=120 games)** — the first net-in-search coupling to beat
the plain champion. IF the fresh-seed extension holds (n=240 combined,
running), the expert-iteration flywheel ignites: vleaf becomes the
gen-v4 teacher and the distillation ceiling moves above mc for the
first time. Mirage protocol applies (v5-hybrid: 55% preview reversed);
no adoption, no ledger promotion, no celebration until the extension
lands. Note v1 of this exact design failed at 45% with v6's head —
the N=30-trained v7w value head was the difference.

## KEY LEARNINGS (load-bearing; each cost real compute to buy)

1. **Sourcing beats preference.** Every hard-coded "play X first" rule
   measured ≤53% (ties); widening what the search *sees* measured 62%.
   Ballot coverage of human plays went 84.7% → 99.3% in one day
   (`scripts/audit_sourcing.py` is the tripwire). Same shape at the RL
   layer: ballots must be wide at *data generation*, then frozen.
2. **Label quality out-predicts architecture.** bc < distill < N=30
   textbook tracks the checkpoint ladder exactly; capacity (1024-trunk)
   and temperature sweeps were nulls; soft targets (T=0.05) were the one
   recipe fix that mattered (stochastic teacher ⇒ distribution targets).
3. **Ballot/encoding freeze.** Play-time enumeration must match training
   distribution byte-for-byte — the exhaustive-follows change silently
   collapsed a deployed net to Elo 798. Any change ⇒ regenerate,
   retrain, re-verify.
4. **The value pathway is fragile; ask the net small questions.**
   Raw-return regression on a warm start crushed action ordering (spread
   22.5 → 0.26, twice, alarm-verified); net-as-rollout-policy amplified
   tail errors (37% vs mc at 100x cost). Full-information oracle study:
   only 43-47% of outcome variance is predictable at all. Surviving
   net-in-search designs ask one bounded question: value at a truncated
   leaf (vleaf, in gate), world likelihood (belief sampling, queued),
   candidate priors (proposer, queued).
5. **Warm starts are safe iff the objective matches.** v6→v6.1 (same
   distill loss): fine. BC→DMC (raw returns): destroyed the checkpoint.
   v7-warm tests whether "init from incumbent" becomes standing policy.
6. **Strength overfits before val metrics notice.** v6cont: gates fell
   51/41→44/32 while val agreement moved 0.4pt. Model selection =
   per-epoch snapshot **strength probes**, never loss. Peak lands ~ep3-8.
7. **Small samples reverse.** 55% (n=40) → 37% (n=60) killed the v5
   hybrid; 54% (n=200) → 51% (n=400) killed PAIR_VOID_BOSS. Extensions
   are mandatory; and probes only compare *within* one seed batch —
   game-level and round-level rates are not interchangeable (games
   compound round edges: 52% rounds ≈ 88% games vs heuristic).
8. **Direct duels > transitive probes** for close calls (protocol below).
9. **Agreement ≠ strength**, measured twice: v6's val agreement froze
   while strength climbed; wide-ballot mc gained 12pts h2h with
   agreement flat (55%, leads 31% vs 30%). Agreement is a style/sanity
   metric — the tripwire, and the human-blend target — not a strength
   signal.
10. **Elo is pool-relative.** mc rated 1141/1104/1067 across pools with
    no code change. Only within-pool gaps, fixed-seed gates, and direct
    duels transfer between tables.

---

## ROADMAP (ordered)

1. ~~v7 / v7-warm~~ **DONE**: warm won (all 4 snapshots > v6, best
   64.5%; scratch killed at ep1/8). Standing policy: init every
   generation from the incumbent.
3. **MCValueLeaf gate — FAILED (45%, 54-66 n=120 vs wide-ballot mc,
   2026-08-02 evening).** v1 config: 4-trick truncation + v6 value head
   (trained on old-teacher values). Not retired as a pathway: retry
   cheaply with a v7w/v8 value head + truncation sweep, else fall back
   to continuation-strategy leaves. Original design notes: (was running) — truncated rollouts + v6 value leaf,
   vs upgraded mc. Pluribus precedent: depth-limited search with leaf
   evaluation was its enabling trick (5 orders of magnitude compute
   reduction, ran on a 64-core workstation). Poker-transfer variant if
   the plain version falls short: *continuation-strategy leaves* —
   evaluate leaves under k biased rollout policies (aggressive-trump /
   conservative / point-feeding) instead of one, so opponents at the
   leaf get to "choose" their bias (robustness without a net).
4. **Belief-weighted world sampling** — Pluribus updates beliefs over
   hidden cards by Bayes' rule under an assumed strategy. Our version:
   weight determinizations by likelihood that the heuristic (as opponent
   model) would have played the observed actions given the sampled hand
   — computable exactly with no net, generalizes pair_void's hard
   proofs. Gate: weighted-sampling mc vs uniform mc, n=120. Learned
   belief net later if the exact version pays.
5. **Ballot-v2 teacher generation — RUNNING (gen-v3, both machines,
   overnight)** — the dataset fixes all three
   known biases at once: CONTROL_LEADS-era teacher, throws + component
   combos on the ballot (99.3% human-play coverage), TRACTOR_LOCK
   decisions recorded as choice-only samples. Then v8 students.
6. **AWAC-style dmc2 rewrite** — self-play beyond the teacher via
   advantage-weighted policy-head imitation (values stay in their own
   head; the measured-fatal Q-regression pathway never touches the
   policy). Reuses ~90% of dmc2.py, incl. oracle baseline + spread
   alarm + gating (archive: 13-point spec).
7. **Contingency** — if the net line stalls with all of the above:
   encoder audit (aux-head probes) before more training; rented compute
   (fat-CPU actors + GPU learner, 10-30x throughput) only if a curve is
   climbing but slowly.

---

## Training data inventory (2026-08-02, all local + gitignored)

| dataset | size | what it is | teacher | trained |
|---|---|---|---|---|
| `rl_data/bc` | 1.73M decisions / 35 shards / 155M | SmartBot behavior cloning (~20k rounds): obs + chosen action, no values | SmartBot | ckpt_bc, ckpt_bc_dueling |
| `rl_data/distill` | 1.66M decisions / 36 shards / 155M | search distillation: full ballots + MC per-candidate rollout values, N=10 | MCBot (pre-CONTROL_LEADS) | v4, v5, v6, v6.1 base |
| `rl_data/distill_n30` | 1.06M decisions / 24 shards / 104M | the low-noise textbook: same format, N=30 (3x less label noise), pairfix+voiddump teacher | upgraded MCBot | v7 (in training) |
| `rl_data/human` | 801 decisions / 1 shard | FROZEN while v6.1 trains on it — superseded by human_v2 | live humans | v6.1 blend |
| `rl_data/human_v2` | **1,003 decisions** / 1 shard (2026-08-02, post-fly-fetch) | rebuild with **v2 ballots** (exhaustive follows + lead throws): human throws now compete against rival throws | live humans | next blend |
| `rl_data/oracle` | 1 shard / 10M | full-information states + outcomes (own schema) | self-play | oracle value study (43-47%) |
| `../logs` | 21 games / ~1M | raw JSONL — human corpus source, 1,052 decisions and growing (rebuildable in seconds) | live play | audits, agreement, miner |

Key asymmetries: quality ladder bc < distill < n30 tracks net strength;
all 4.4M machine decisions share the v1 ballot's biases (75% follows, no
TRACTOR_LOCK leads, ~0% risky throws) — roadmap #5 fixes all three; the
human pile is 4,000x smaller but highest signal-per-byte.

---

## Measurement rules (non-negotiable)

- Mirrored deals everywhere; n≥120 round-level or n≥200 games; ties
  (<55%) are not adopted — EXCEPT menu-widening changes, which adopt at
  neutral (they compound with future evaluation improvements; preference
  rules must pay now).
- **Strength vs selection (v7w lesson, 2026-08-02):** STRENGTH claims
  come only from anchor pairings vs smart AND mc (round-level).
  Net-vs-net duels against the incumbent are for SELECTION among
  sibling checkpoints and tiebreaks — descendants exploit ancestors
  (v7w: 64.5% over v6, yet ~v6-level on anchors), so a family duel is
  never a ladder claim.
- **Partial-checkpoint protocol:** every snapshot gets (1) fixed-seed
  round-level probe vs current SmartBot (n=60, compare only within a
  seed batch) AND (2) a direct mirrored duel vs the incumbent best net
  (n=200). Blend checkpoints also get the human-agreement eval.
- Policies rated in Elo pools, never a single opponent; pool numbers are
  pool-relative; promotion to server default requires a full-game
  mirrored match vs `mc`.
- Negative results are archived, not deleted (`server/runs/`,
  AI_POLICIES experiment log).

---

## ARCHIVE (chronology, compressed — details in git + server/runs/)

**Phases 0-2 (complete):** fast env (2,067 rounds/s multiproc); 531-dim
obs + 60-dim action encoding (ENC_VERSION 1); exhaustive follow + v2
lead enumeration; BC gate passed (89.7% imitation → 48% vs smart / 29%
vs mc — search exploits clone errors; encoding carries the game).

**DMC v1 (closed):** warm start + raw-return regression = flat 30-34%
over 400k rounds; value regression crushed BC ordering (spread
22.5→0.26); degraded policy then fed itself. `server/runs/dmc_v1.md`.
Root insight: DouZero trains from scratch; AlphaGo 2016 kept SL/RL nets
separate for exactly this reason.

**Distillation series:** v1 32/22 → v2 (+CE temp) 30/27 → v3 (split
heads) 32/24 → v4 (+soft targets) 38/32 → v5 (full data) 42/38 → **v6
(12 ep) 51/41** — no bend in the curve until data ran out. Diagnosis:
teacher is stochastic and ~70% of labels are SmartBot-via-margin; soft
targets average the teacher's RNG.

**Snapshot sweep:** 20-epoch run probed per epoch: 38% ep0 → 53-57%
plateau ep3-10 → wobble after. v6cont (6 extra epochs) NEGATIVE (44/32).
Strength peaks early; probe-select thereafter.

**Hybrid v1 (net rollouts): dead.** 55% preview (n=40) reversed to 37%
(n=60); bare v5 out-rated its own hybrid in-pool (1088 vs 1074); "feels
wonky" preceded the stats.

**dmc2 (halted twice by its own spread alarm):** the 13-point recipe
(dueling split, Suphx oracle baseline, annealed anchor, gating, opponent
pool, aux heads, ballot freeze, spread alarm, oracle upkeep, ε schedule,
replay cap, run bookkeeping) remains the AWAC rewrite's scaffolding —
the alarm works (caught spread collapse in 2 min); the Q-regression
core is what AWAC replaces.

**Overnight sweeps (2026-08-02):** temperature 0.03/0.10 null; 1024
trunk null; MC-level stack validation 57% (heuristic-level h2h testing
inherits to MC); RISKY_THROWS/TRUMP_BALLOT 53%/53% solo (superseded by
wide ballot).

**Historical pools:** 2026-08-01 A: mc 1141 > rl-v5 1088 > mc-v5roll
1074 > smart 1055 > heuristic 1000. Pool B: mc 1104 > rl-v6 1032 >
smart 1006 > heuristic 1000. 2026-08-02 night: mc 1067 > smart 1061 >
rl-v6 1023 > heuristic 1000 (heuristic adoptions closed most of the
search's margin). Cross-pool numbers do not compare.

**Play-test notes:** Jerry vs v6 live (2026-08-02): "some passive plays
but feels decent" — corroborates the 75%-follow dataset bias; fixes:
lead-weighted loss arm, ballot-v2 teacher data.
