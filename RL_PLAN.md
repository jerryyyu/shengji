# RL Plan: training a learned Sheng Ji policy

Goal: a neural policy that **beats MCBot in the Elo tournament pool**
(the standing "Elo > 1137" milestone — pool-relative, so operationally:
rl above mc in the same pool). Hardware: one Mac mini (M4, 10 cores,
MPS). Everything measured: mirrored deals, fixed-seed probes, direct
duels, Elo pools, human-agreement tripwire. Toggle-level results live in
AI_POLICIES.md; run archives in `server/runs/`.

---

## STATE OF PLAY (2026-08-02, end of day 3)

**Prod (deployed tonight): mc with BOTH wide ballots** — leads 62%
(75-45) + follows 60% (72-48) over its prior self in one day; pool 1109.
Sourcing coverage of human plays 84.7% -> 99.3% (audit_sourcing.py).

**Nets — rl-v7w is the new best** (warm from v6, 4 ep on the N=30
textbook, ~1.5h): beat v6 in all 4 snapshots, best ep02 64.5% (129-71,
n=200). Warm-start = standing policy (~5x iteration). CAVEAT: pool
anchors put v7w ~v6-level (45% vs smart, 32.5% vs wide-mc) — net-vs-net
game duels overstate transitive strength (nontransitivity + game/round
amplification). The mc-net gap is NOT closed; mc gained more today than
the nets did.

**Running overnight: gen-v3** — 28k+12k rounds on Air (7 workers) +
mini (6 workers, worker-offset), N=30, full wide-ballot teacher,
ballot-v2 throws, TRACTOR_LOCK choice samples, META provenance. The
first textbook written by the 1109 teacher; v8 trains WARM from
v7w-ep02 on it.

**Today's other verdicts**: 9-entrant distributed pool (Air, chunked,
~40min) — table in AI_POLICIES; v6.1 human-blend: +6->+8 agreement
across epochs (51->57->59%) at ~2-4pt strength tax, stopped at ep2,
rerun later on v8 + human_v2; vleaf v1 FAILED gate (45% vs wide mc —
retry with v7w value head); heuristics batch 1 (ACE_SEQ,
NO_OPEN_POINT_SUIT) both exact ties, off; expert-strategy research
(9 ranked candidates) + ShengJi+ review in server/runs/.

**Fleet**: mini + Jerry's MacBook Air (ssh, Tailscale; higher security
bar — see memory + ~/air-link.md). JOBS.md per machine = job ledger +
inter-agent mailbox; fleet_status.sh = one-command live status; hourly
utilization cron + daily 8:53 maintenance (session-scoped).

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
