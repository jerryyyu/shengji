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
- [x] Step 2 bwc port: PR #1161 head 64159b86 (branch claude/s68-bwc, pushed). Search-regression set (66 modules) with REQUIRE=1 +
      smv3out/S17/S58: pure 1588 passed / 17 skipped; compiled 1622 passed / 3 skipped; test_pv_belief_capacity 13/13 both engines, 0 skips.
      Ask body: ~/.claude/jobs/d0498cda/tmp/s68_bwc_pr_ask.md (not posted)
- [x] Step 3 candidate tree claude/s68-cand 8b6ead10 (pushed) = 64159b86 + merge of #1156 39d514cc; name_probe.out, local_blocks_check.out rc 0
      B = ...-bw-bwc-...-red111e2f-...-9125072c7686-sc8 (diff belief_capacity); A = w96-k12 ... lgfd1000 ... r99a6f365 ...-sc8
      (diff belief_capacity, candidates 12, lgfd 1000, serving 1.5, worlds 96; bury budget 1.0); defender R48 plain draw
- [~] Step 4 packet tools/s68dev/ (commit on claude/s68-combo):
      perf: tree staged (8 files) + built (BUILD_RC=0, ext 3d8134f4/b3d33104/1cb0bf4d); final launcher 2adc5531; final reader 35a820da
      rehearsal on perf 13:08-13:13Z both arms VALID, 0 fallbacks; b 134.7 s/56, a 176.2 s/56 (max 1.33 s vs 1.5 budget); host DRYRUN rc 0
      lane_lint --packet: 0 findings; staged-layout test ALL PASS; packet test ALL PASS; launcher fresh ALL PASS
      seeds B 243660910+3920 / A 244060910+3920 / reh 243570000+56: registry rc 0, exact-deal CLEAR x2, host reservations clean
      pending: reader e2e tests (per arm) + battery (per arm) running; lane phase NOT staged; no RELEASE, no waiter
