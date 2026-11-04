# ShengJi+ (Berkeley EECS-2023-127) review — 2026-08-02

**Can we play their model? No.** Only checkpoint link (jiaruishan.com)
is NXDOMAIN, never web-archived; no releases/LFS; all 9 forks weightless.
Training code only. Even recovered, low value: validated only at 97.6%
vs RANDOM, author admits weak throw play, and 3 rule mismatches make
head-to-head unfair (kitty multiplier 2^pattern up to 64x vs our 2xsize;
chaodi 抄底 enabled; failed throws become public info; ≤3-pattern cap).

**Their method** (worth reimplementing as a pool baseline, ~2-4 days on
our 531/60 interface): DouZero-style DMC, 4 phase nets (declare/kitty/
chaodi/main), LSTM over last 15 tricks, sequential sub-actions for
kitty/throws, dense per-trick point deltas + terminal reward = LEVELS
GAINED, γ=0.95, RMSProp 1e-4, ε=0.015. DMC beat DQN 69.5/59.7.

**Steal list:**
1. Terminal reward = levels gained (encodes 40/80 brackets) + dense
   per-trick point deltas — upgrade for our returns.
2. γ=0.95 sweet spot (γ=1 too noisy, ≤0.9 blind to kitty endgame).
3. Their measured NEGATIVES: oracle-guiding HURT (93.4 vs 97.2 — matches
   our oracle skepticism); max-entropy bonus HURT (many-legal-actions
   correlates with dominated states); combo penalty best at 0.
4. Richer-action training transfers: multi-pattern-trained beat
   single-pattern-trained EVEN in single-pattern play (52-48) —
   independent validation of ballot-v2 for gen-v3.
5. Trump-relative dynamic card encoding (canonicalize obs by trump) —
   no LR gain but better AAPD; candidate for ENC v2.
6. AAPD (avg attacking-point difference) as fine-grained metric beside
   win rate.

Action items: polite GitHub issue to TheMoon2000 asking for 1180000
weights (fire-and-forget); DMC-recipe baseline reimplementation queued
behind AWAC in RL_PLAN.
