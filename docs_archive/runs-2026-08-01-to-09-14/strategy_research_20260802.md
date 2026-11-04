# Expert-strategy research (2026-08-02, background agent)

Ranked candidate heuristics from Chinese guides (Baidu Jingyan, gameabc,
91y dealer series, Sina 十大原则, CFC signaling thread, Sohu inference
articles) + Ben Zhang's English guide + Berkeley ShengJi+ thesis. Each
becomes a toggle → duel gate as usual.

1. **ACE_SEQUENCING (HIGH)** — attacker with boss cards in several side
   suits: cash aces in suits the dealer team still follows BEFORE aces
   in their likely-void suits (order by void risk: my length + seen).
2. **KITTY_POINT_POLICY (HIGH cap / MED aggressive)** — banker: trump
   <13 → bury ≤5 points, pointless singles; strong lock (≥13 tr, 3+
   pairs, boss) → deliberately bury unprotectable 10s/Ks (2x multiplier
   banks them).
3. **NO_UNFINISHABLE_POINT_SUIT (MED-HIGH)** — dealer team never opens a
   side suit with outstanding points + no boss + can't run it; leave it
   for opponents. Veto filter in the lead hierarchy.
4. **TREE_PLANTING 树套 (MED)** — ≥6-card side suit with AA / A+KK: lead
   LOW from it early to exhaust the suit, cash retained tops late.
   OVERRIDES control-leads' pairs-first for these hands.
5. **NT_ON_POINT_RANKS (MED)** — joker pair on rank K/10/5 → declare NT
   eagerly (joker-pair lead forces point drops); avoid NT otherwise
   (NT favors attackers).
6. **ATTACKER_LOOSE_THROWS (MED)** — role-asymmetric 甩牌 gate: keep
   provable-only for dealer team, allow small-risk throws as attacker.
7. **PARTNER_SIGNALS (MED-LOW)** — >7 follow under partner's winning A
   = "continue suit / I hold the other boss"; low = switch. Emit + read
   (self-consistent between our bots).
8. **K_CONCEALMENT (LOW-MED)** — partner leads A, I hold K with ≥5 in
   suit → don't drop the K (guard it); ≤3 in suit → K is fine.
9. **GATED_SLAM_DRAIN (LOW, flagged)** — ONLY with ≥4 trump pairs (or
   14+ trumps, 3+ pairs, boss side suit): consecutive trump-pair leads
   to void the table, then run winners. Heavily-gated exception to the
   REJECTED early-trump-drain; drop if <50%.

Excluded deliberately: "feed points into partner's voids" (contradicts
two measured rejections). Endgame trump-control rules ~subsumed by
ENDGAME_CONTROL + search.

Sources: sohu.com/a/396138006_120099904 · m.sohu.com/n/448262530 ·
jingyan.baidu.com/article/fa4125ac0e8f2928ac7092b3.html ·
gameabc.com/news/201704/3372.html · 91y.com dealer series 1643/1644/1645 ·
blog.sina.com.cn/s/blog_65133e280102yayu.html · CFC bbs threads/73055 ·
Ben Zhang "An Introduction to Sheng Ji" PDF · Berkeley EECS-2023-127.
