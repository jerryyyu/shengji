# Code-lane cleanup, 2026-09-05 (issue #235, section 3)

Removed the closed code lanes from the tree.  Nothing is moved into an
in-repo archive folder: Git history and the tag
`archive/code-lanes-pre-cleanup-20260905` (created on the merge-base with
`main`, i.e. the last pre-cleanup main commit) keep every deleted file, as do
the existing `archive/pr-*` tags.

## Removed (line counts as on main before the cleanup)

| Removed | files | lines |
|---|---|---|
| belief lane: `rl/belief_*.py` (69), `scripts/belief_*` (5), `tests/test_belief_*` (53) | 127 | 46,741 |
| scripts `s3a/s3b/s3c_*` (+tests, `tests/data/s3b_*`) | 23 | 16,506 |
| scripts `teacher_*` (+tests) | 21 | 13,437 |
| scripts `pair_ballot_*` (+tests, `tests/data/pair_ballot_retention_census.v1.json`) | 22 | 11,146 |
| `review_*_terminal`, `terminal_review_common`, `live_champion_parent`, `report_lcb_replay_benchmark` (+tests, `tests/data/report_lcb_caxi_replay.*`) | 10 | 8,673 |
| `rl/suphx_*` (8) + 2 scripts + 8 tests | 18 | 8,241 |
| scripts `s0_*` (+tests, freeze jsons) — except `s0_override_audit.py` | 19 | 7,615 |
| scripts `h0_*` (+tests) | 7 | 6,463 |
| scripts `v11_*` (+tests) | 9 | 6,347 |
| early-August one-off scripts (38: heur2/3, pool_*, v8_battery, vleaf_v9, vleaf_variants, gate_*, label_noise, capacity_sanity, residual_eval, highn_*, refit_override, t3_gate_screen, aggregate_shards, attribute_residual, paired/reweight/sampler_posterior, representativeness, mine_disagreements, audit_sourcing, bench_fast, profile_fast_round, analyze_human, eval_vs_human, smoke_ws, gen_voices.sh, corpus_split, decision_sensitivity, ballot_coverage) | 38 | 4,485 |
| scripts `s4_*`/`s5_*` (+tests) | 10 | 5,821 |
| `rl/douzero_learning_screen` + script + test | 3 | 2,912 |
| `pilot_run`, `pilot_aggregate`, `shengji/pilot_{arms,score}` (+tests) | 8 | 2,566 |
| scripts `rlcb_c1*` (+tests) | 5 | 2,047 |
| dead rl lineage: `rl/{bc_train,dmc2,fastenv,oracle,segbatch}` | 5 | 922 |
| `rl/distill_{generate,train}` | 2 | 443 |
| **total deleted** | **327** | **~144,400** |

Also: `PRIVILEGED_TEACHER_V1_PROPOSAL.md` moved to `docs_archive/` (PT1 is
negative for its frozen scope per BACKLOG); `tests/test_selfplay_contract.py`
drops its four `dmc2` tests; `tests/test_v11_anchor.py` drops the four tests
that needed `v11_revalidate`/`teacher_v1_states`.

## Kept although the proposal marked it (dependency found)

| Kept | Why |
|---|---|
| `rl/torch_policy.py` (incl. `MCValueLeaf`), `rl/model.py`, `rl/npnet.py`, `rl/provenance.py`, and the registry rows `mc-vleaf-v7w-ep02`, `mc-vleaf-v13abs`, `mc-vleaf-v8a-ep03`, `rl`, `mc-v5roll`, `mc-race*`, `rl-override-*`, `mc-v11anchor*`, `mc-gate-v11pair` | The checkpoints they name still exist (`~/Projects/shengji/server/{snapshots_v7w/ep02.pt, ckpt_v13abs.pt, snapshots_v8a/ep03.pt, snapshots_v11pair/ep07.pt, snapshots_v10res/ep09.pt, ckpt_distill_full.pt}`; `server/snapshots_v11pair/ep07.npz` is tracked).  The removal condition ("checkpoints do not exist anywhere under the repo") is not met, so the rows and their module stay; `tests/test_v11_anchor.py` and `tests/test_npnet_*` keep covering them. |
| `rl/human_shards.py` + its imports `rl/bc_generate.py`, `rl/dataset.py` | `MAINTENANCE.md` and `README.md` name `python -m shengji.rl.human_shards` as the builder of the `rl_data/human_v8` corpus that `harvest/human.py` reads. Follow-up: inline `round_value`, `Decision`, `TrajectoryWriter` into `human_shards` to drop the other two. |
| `rl/douzero_micro.py` | imported by `rl/value_afterstate`, `rl/value_model`, `train/cwv_*` (load-bearing, as the proposal notes). |
| `shengji/teacher_v1.py` | imported by `rl/value_afterstate`; its module-only tests now live in `tests/test_teacher_v1_module.py`. |
| `scripts/pilot_states.py`, `shengji/pilot_folds.py`, `shengji/state_replay.py` | imported by the kept engine/sampler tests (`test_invariants`, `test_sampler_constraints`, `test_pilot_freezer`, `test_pilot_folds`) and by `scripts/capture_deep_leads.py` (not on the removal list). |
| `scripts/s0_override_audit.py` + `tests/data/s0_override_audit.v1.json` | the predeclared DEV calibration that chose `S0_REPORT_WORLDS` (registry comment, CORRECTNESS.md). Its two tests now live in `tests/test_s0_override_audit.py`. |
| `scripts/certify_sampler.py`, `scripts/capture_deep_leads.py`, `scripts/xray.py`, `bench_mc_*` | cited by CORRECTNESS.md / tested / not on the list. |
| `rl/replay_log, actions, exact_resume, selfplay_contract, synchronous_selfplay, encode, encoder_identity` | live importers verified (harvest, engine/ballot, douzero_micro, value_*). |
| `luna/*`, `ai/legacy_b3f8f61` | kept for now per the proposal (registry pins the legacy policy). |

## Safety witnesses

1. **Import walk** — new `tests/test_import_walk.py` imports every module
   under `shengji` (101 modules): all pass; added to the pure-mode PR check.
2. **Stale references** — `grep -rnw` for every removed module/script stem
   (outside `docs_archive/`, `handoff_archive/`, `incidents/`,
   `HANDOFF_REVIEW.md`) finds only prose (RL_PLAN archive boundary, two code
   comments naming the former `highn_build`/`bc_train` methods, a schema
   string `dmc2-clipped-level-possession-v1`, and the kept data file
   `rl_data/corpus_split.v1.json`).  No `shengji.rl.<removed>` or
   `scripts/<removed>` path remains.  No registry name was removed.
3. **Full pure-engine suite** (`SHENGJI_FAST` unset, single process):
   - main @ `ead2007d` (pre-cleanup base): **2578 passed, 29 failed, 58 skipped**
     (24:49).
   - branch: **1144 passed, 13 failed, 31 skipped** after settling (the raw
     run, 1144 passed / 19 failed / 31 skipped, started before the rebase onto
     #233 and before the `STATE_SCHEMA` import fix; the six extra failures —
     `test_luna_runtime` ×4 and `test_harvest_trajectory` git-identity stamps,
     `test_teacher_v1_module` ×2 — re-run green on the settled tree).
   - The 13 remaining branch failures are the same 13 that fail on main in
     this environment: `test_heuristic_lead_native` ×4 (needs the compiled
     engine), `test_invariants::test_acting_team_sign_is_correct_for_both_roles`,
     `test_sampler_constraints` ×2, `test_pilot_freezer`, `test_npnet_parity`
     and `test_vleaf_leaf` (gitignored corpora/checkpoints absent in a clean
     checkout), `test_report_lcb_perf_accepted_stack_receipt` and
     `test_review_authority_inventory` (source-byte receipts that predate
     later main commits).  The 16 main-only failures were all in removed
     campaign tests.
   - `tests/test_cwv_puct.py` (merged on main after the base) passes on the
     branch (127 passed with the import walk and `test_cwv_policy`).
4. **Fast engine** — `python setup.py build_ext --inplace` builds; the CI
   compiled-parity list passes (124 passed, 2 skipped) and the CI pure list
   passes (338 passed, 2 skipped, incl. the import walk).  Luna CI lists pass.
5. **Production bot parity** — `mc` and `mc-s0-report-lcb`, seeds 20260905 and
   20260906, `shengji.ai.env.play_round` on main and on the branch: history
   and result sha256 identical byte-for-byte for all four rounds.
