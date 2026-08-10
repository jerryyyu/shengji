# Active Claude/Codex handoff

Last compacted: 2026-08-09 20:21 EDT. This is the executable mailbox.
Terminal markers live in `HANDOFF_REVIEW.md`, policy synthesis in
`AI_POLICIES.md`, live jobs in `JOBS.md`, and queue order in `BACKLOG.md`.

## Current truth

| area | status | next legal action |
|---|---|---|
| Production | **LIVE / CONFIRMED** | Fly release 17 runs compiled `mc-s0-report-lcb`; no production change is open. |
| S3a structured bury | **TERMINAL VERIFIED / SELECT NONE** | The exact original verifier returned `verified=true` at 20:20 with aggregate `20609613…271f` and final `32156d79…c9ff`; preserve `+0.0464`, LCB `-0.0041`; no retry, tuning, pooling or confirmation. |
| S4 point banking | **SEALED MINI SCREEN RUNNING** | Exact `cad3992`, packet `17036e63…1385`, receipt `20a420d2…5cc`; 750 count-only shard lines at 20:21 with eight CPU-bound workers. Do not inspect partial outcomes. |
| Human H0 | **V2 REVIEW LOGIC PASS / OPERATIONAL HOLD; V3 REVIEW OPEN** | The v2 admission tombstone dirties Git and makes runtime reopen impossible. Review PR #6 source `4ebcd09` plus packet `cf074871…35392`; do not issue a receipt. |
| Teacher Stage C | **V3 DESIGN PASS / ZERO STATES / REBIND FREEZE BLOCKED** | Claude passed design packet `f213314a…3b4`. Score-free bridge source `7018f36` is prepared with 105 tests: it binds the immutable design plus H0-v3/S3c-v2 without copying curriculum fields. A real packet still requires both replacement PASS markers. |
| S3c small endgames | **V1 REVIEW LOGIC PASS / OPERATIONAL HOLD; V2 REVIEW OPEN** | The same tombstone bug blocks v1. Review PR #6 packet `cafbee43…f23e`; do not issue a mechanics receipt. |
| S5 point protection | **BOUNDARY FIXTURE PUSHED / RE-REVIEW OPEN / NO CENSUS** | PR #4 head `2351b36` adds a real lower-ranked-but-equal-point witness and mutation proof. Re-review before one deterministic census freeze. |
| HUMAN-C1 | **PARKED / NO TRAFFIC** | Resume only after a challenger beats report-LCB in confirmation. |

## Why Stage C matters after it is executable

Stage C is a Teacher, not a deployable bot. It creates 2,048 fresh,
split-safe counterfactual examples where ordinary choices get the certified
cheap grader and uncertain/disagreement/point/bury/endgame choices get deeper
common-world comparisons. We then:

1. train at least eight seeds of separate within-ballot ranking and calibrated
   signed-outcome heads, with bury separate;
2. choose architecture on DESIGN and one recipe/checkpoint rule on CALIB;
3. open the untouched 512-state REPORT fold once;
4. if a head passes, use only that capability inside report-LCB—first to add or
   rank a bounded number of candidates, then optionally to allocate search;
5. retain the incumbent and let fresh disjoint MC report worlds make the final
   LCB decision; compare with a same-work random/null arm;
6. require a fresh whole-game screen and confirmation against
   `mc-s0-report-lcb` before promotion or a blinded human ladder.

A ranking PASS with calibration failure may propose/rank but may not steer
value/allocation. The first 2,048 rows prove the learning/composition mechanism;
10k/50k collection is conditional on untouched offline gain plus whole-game
gain, not automatic scale.

## Review priority 1 — controller admit-to-runtime repair (PR #6)

### Root cause and repair

H0-v2 and S3c-v1 correctly publish a durable consumed-slot before their
receipt, but `server/runs/locks/` was untracked and unignored. Every subsequent
runtime packet open therefore refused the tree it had just dirtied. The old
admission tests patched out the real opener and missed the failure.

PR #6 versions H0 as v3 and S3c as v2. Exact `.gitignore` bytes are part of
both transitive source manifests; each runtime proves its concrete lock path is
ignored, then still rejects all other tracked or untracked dirt. New tests run
real admit -> packet reopen and separately turn both unrelated untracked and
tracked changes red. The frozen Stage-C-v3 validator now uses literal H0-v2
evidence identities so historical packets remain reproducible rather than
silently inheriting moving constants.

### Exact assets and measured checks

- PR: `https://github.com/jerryyyu/shengji/pull/6`;
- executable source commit: `4ebcd09111af0ef76ffd6f862764f28b275e4383`;
- packet commit: `1933c65` (packets remain bound to source `4ebcd09`);
- H0-v3 packet: external/internal `cf074871cf977c0b072c528c395082b453b3b589f445c524baae9016e1d35392` / `757ac2732f3051978aee0fde2daf74ebc1d689ba1050eb2f8e46e3a787b045b2`; 557 rows, zero worlds/outcomes;
- S3c-v2 packet: external/internal `cafbee439f8c30a07b0b6801d52620d7197afc3633badbc531bc5b156ce2f23e` / `8c8717fd4c4a5af6514d680c8ded30cb4b1ed472b0a69fc894d0d02cf22adb2d`; 64 roots, zero worlds/solver sessions;
- 97 focused H0/S3c/endgame/Stage-C tests pass under compiled strict-void mode;
- full-suite collection reaches unrelated ignored-model assets absent from the
  isolated worktree; no failure was in this change's transitive battery.

Review the packet bytes from `1933c65` against an exact clean `4ebcd09`
source checkout with canonical RLCB-C1 evidence/native bytes. Recompute both
packets, mutation-test the new lock boundary, and confirm Stage-C-v3 still
reopens its historical H0-v2 evidence. PASS authorizes one later H0 diagnostic
receipt and one later S3c mechanics receipt only. It does not authorize either
receipt now, Stage-C capture, labels, training, strength, promotion or prod.

Requested markers:

`H0_HUMAN_COUNTERFACTUAL_CONTROLLER_V3_REVIEW {"admission_slot_logical_path":"server/runs/locks/human-v8-h0-counterfactual-execution-v3.consumed.json","candidate_geometry_sha256":"876ed56bd8f436d58cb6f3d58774a0f06756afb4d8c98ffdb49d9424b545ff2b","compiled_fast_binary_sha256":"9c9e77fbdc4c6caceec195465155f37ec6369e409462fd838bc142bf8a0be4c1","controller_script_sha256":"ff06b7b9e46d0fef71a9b7d19b31caa3d7d1d073da2f573111252548dfcced6b","corpus_manifest_sha256":"b9699790bdfe1c217922c9f9c72b237c1856174fa64c11753329a8ff11e16553","deletion_proof_one_shot":true,"design_packet_sha256":"4d3f0a35082c6957f2a468686b8eedbd6d7cbbf9540503fcea08cccf27c8cc3c","design_review_git":"239f13ce52a8be81108fdebf9bd0e96742e60133","fast_router_sha256":"f2506d5c51b8ad37303f04dce59899de0d7c1179633b08ce61f48eb86cec1a3e","git":"4ebcd09111af0ef76ffd6f862764f28b275e4383","independent_review":true,"labels_authorized":false,"max_candidate_worlds":1329210,"one_counterfactual_execution_authorized":true,"outcomes_computed_before_review":false,"packet_sha256":"cf074871cf977c0b072c528c395082b453b3b589f445c524baae9016e1d35392","production_deployment":false,"production_promotion":false,"runtime_script_sha256":"a85a217977a1bf1523c4f7bd7748abe1048c8bf70b4d78670e7b75970eefa371","schedule_sha256":"f54ce37425707dfeea3563bbc5d635617943152166a82825a74e55ad00131793","schema":"human-h0-counterfactual-controller-review-v3","score_free_preflight_verified":true,"selected_bury_rows_sha256":"cdfe77dfbec0e97fb8935c5822239acd6db60c644c433c32a4445913459aa1e8","selected_play_rows_sha256":"18673b20ca0a5b1a8e476f3bcf45cf9d08f90f4244f9c5ee07cb8bd8cd47711d","source_manifest_sha256":"07ff18fb35f2fb987f18b37b5100172e2751681fbfed17285ce7d7035232aa5e","strength_claim":false,"strict_runtime_verified":true,"training_authorized":false,"v11_checkpoint_sha256":"cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003","verdict":"PASS","worlds_sampled_before_review":0}`

`S3C_ONE_CARD_CAPACITY_CONTROLLER_V2_REVIEW {"census_sha256":"236326099dc9763c6a5941bcb2a90670c4e23ac390ea07a0e4ec5063fa50b52a","controller_script_sha256":"2d011829b5d1a1d8a99c45558873a5ed23df2f1dedfeec65dd3a4bed60ce3664","design_packet_sha256":"df1024280a77c60174a57c3273ba3624e672bec9afde023576fde0404df49eca","design_review_git":"084ba7eba59cd0a317a50c4088f194d2376c1e03","exact_solver_sessions_before_review":0,"git":"4ebcd09111af0ef76ffd6f862764f28b275e4383","independent_review":true,"max_execution_nodes":65536,"max_terminal_replay_nodes":65536,"one_card_capacity_execution_authorized":true,"outcomes_computed_before_review":false,"packet_sha256":"cafbee439f8c30a07b0b6801d52620d7197afc3633badbc531bc5b156ce2f23e","production_deployment":false,"production_promotion":false,"root_geometry_sha256":"b2599bb50d8e2bd2762ac73af3206749e1f446eb5b971c1562e706883e48be0b","roots":64,"runtime_script_sha256":"3c4972d0c5a4022b3f7cb5795b255f801786ab0a062341c2aecef33594c4109d","schedule_sha256":"8257499b8b613d02c899161bfd8ffac5579336dc54239ab443dfe5a7fad5e7de","schema":"s3c-one-card-capacity-controller-review-v2","score_free_preflight_verified":true,"solver_or_strength_screen_authorized":false,"strength_claim":false,"training_authorized":false,"two_card_packet_review_authorized":false,"verdict":"PASS","worlds":256,"worlds_sampled_before_review":0}`

Append measured PASS/HOLD only to `HANDOFF_REVIEW.md`.

## Review priority 2 — S5 boundary-fixture re-review

PR #4 head `2351b36` adds the required real replay/legal witness. The bot
historically plays `HK` under an opposing `HA`; lower-ranked `H10` is a legal
follow, both actions carry exactly 10 points, neither can win, and the row must
remain **not a trigger**. The fixture pins legal/minimum counts, zero avoidable
point delta, current and logged ballot booleans, terminal trigger and null
classification. Deliberately weakening all three strict comparisons from `<`
to `<=` makes this test fail (`lower_point_legal_count` becomes two).

Measured on exact PR head:

- focused S5: 12/12 pass;
- S5 + engine + ballot + live-parent battery: 52/52 pass, with one unrelated
  legacy value-leaf test deselected because this isolated worktree lacks the
  ignored `snapshots_v7w/ep02.pt` asset;
- `git diff --check` clean; production source is unchanged from reviewed
  `c7bba40`.

Please re-review only commit `2351b36` and confirm the equal-point witness is a
genuine cheaper-card boundary and turns the named `<`→`<=` mutation red. A
PASS authorizes one deterministic score-free census freeze only; no S5
treatment, Stage-C eligibility decision, strength compute or training follows.

## Queued after review — Stage-C dependency bridge

Branch `codex/stage-c-controller-rebind`, source `7018f36`, contains a
score-free bridge implementation and eight focused tests. The bridge consumes
the exact passed Stage-C packet `f213314a…3b4` plus exact reviewed H0-v3 and
S3c-v2 packets; it stores only hashes of the original objective, population,
candidate, label, work, gate and execution contracts, and declares every
curriculum delta false. The combined Stage-C/H0/S3c/endgame battery passes
105/105 under compiled strict-void mode. Do not review or freeze a real bridge
packet yet: it intentionally refuses until both controller PASS markers exist.

## Fleet and safety

- Mini: S4 only; count/status checks until all eight workers stop, then one
  exact terminal verifier.
- Air: idle and available for review reproduction or another separately
  reviewed bounded job; no unregistered strength launch.
- Do not create H0/S3c consumed slots or receipts before v3/v2 review PASS.
- Do not capture or label Stage C until a reviewed H0-v3/S3c-v2 rebind packet
  passes without changing the curriculum estimand.
- Never retry, extend, tune from or pool a consumed one-shot stream.
