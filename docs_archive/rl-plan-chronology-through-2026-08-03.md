# RL_PLAN chronology, archived 2026-08-03 23:15

Day-by-day narrative moved out of RL_PLAN.md to keep the live plan
readable. Every load-bearing conclusion is in RL_PLAN's KEY LEARNINGS;
this is the record of how each was reached.

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
