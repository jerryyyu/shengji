# S68 combo candidate — progress
Authority: Jerry 2026-10-26 in Claude's session "The combo and red team sound good to test" (testing only).
- [x] worktree claude/s68-combo from origin/main d33bfd70
- [x] PHASE 1 composition survey -> /Users/jerryyu/.claude/jobs/d0498cda/tmp/s68_survey.md
      primary S68-A = R48+sc8+bwc(S58 port)+w96k12 @ candidate half budget; fallback S68-B = R48+sc8+bwc
- [x] PHASE 2 approved by coordinator (both arms A and B).
- [x] Step 1 bwc offline precheck (Mini, no games) — **PASS**
      script/result: ~/.claude/jobs/d0498cda/tmp/s68/bwcpre/ (SHA256SUMS); draw code = the port in ~/Projects/shengji-wt/claude-s68-bwc
      S58 s58-e6-42444515 (stored T), served BeliefProposal + real draw constraints; 520 heuristic rank-mixed deals
      (ranks 2..A cycled, half first-round / half fixed-banker, seeds 990000000+520), 6,623 non-banker hidden-kitty states, 64 worlds each, same seed both draws
      leak plain 0.178 [0.173, 0.183] trumps/world (bar >= 0.10: PASS); capacity 0.099; cut 44.2% [43.2, 45.3] (bar >= 40%: PASS)
      true kitty trumps 0.000/deal (heuristic bury); rank2 0.162->0.093, rank!=2 0.179->0.100; tricks 0-4 0.223->0.056, 5-14 0.209->0.113, 15+ 0.094->0.090
      caveat: heuristic-play states, not R48 play; cut is near the bar (CI lower 43%)
- [ ] Step 2 bwc port PR (worktree claude-s68-bwc, branch claude/s68-bwc)
- [ ] Step 3 candidate tree main + bwc + sc8 (#1156 39d514cc)
- [ ] Step 4 packet + lane_lint + perf rehearsal
