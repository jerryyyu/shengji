# Active Claude/Codex handoff

> Current queue only. Historical reviews belong in `HANDOFF_REVIEW.md` and Git
> history. A request not listed here is not active.

Last reconciled: 2026-08-17 21:40 EDT.

## Immediate objective

Obtain one consolidated PASS for the outcome-free R2 operator failure, the
split-aware external supervisor, and fresh R3 freeze. That one PASS authorizes
Codex to initialize and execute R3 once. No intermediate review is requested.

## Top/only Claude ask — V2 R3 operator repair + freeze `fbd1fa21…d2c2c`

Perform one read-only review on `shengji-cloud`. Do not initialize R3, start
workers, reuse R1/R2 artifacts, merge PR #119, open any test/scientific result,
deploy, or grant gameplay/strength authority.

### 1. Authenticate spent R2

- R2 receipt:
  `/opt/belief-v1-v2-failure-15cc-r2/receipt.json`, root-owned 0400,
  SHA-256 `f54ed7f06c35e6a58162513d956d3139fdf537deccd3240d74a2d7033262ba9c`.
- Independently reopen its full evidence/ops tree bindings and the bound
  status/failure log. Require exact failure
  `operator_human_reference_task_matrix` /
  `V2 human reference split/replicate drift` at
  `human-reference-AIMX-test-primary`.
- Confirm the external R2 supervisor incorrectly formed the 30-source ×
  3-replicate Cartesian matrix. The frozen contract permits only two
  calibration replicates for each of 3 calibration groups, one test-primary
  replicate for each of 3 test groups, and no reference for 24 train groups.
- Require: 0/30 training epochs in all four partial cohorts; no sealed training
  cohort; no calibration, `terminal.partial`, terminal, scientific result, or
  test-decision opening. R2 is spent, preserved, and neither retry nor artifact
  reuse is authorized.

### 2. Review the complete R3 external plan once

- supervisor:
  `/opt/belief-v1-v2-freeze-15cc-r3/ops/supervisor.py`, SHA-256
  `87242f268ec69141baabb36c36dbf8aeb8f275c1984116f0ff06d120b58fa558`;
- contract/mutation witnesses:
  `/opt/belief-v1-v2-freeze-15cc-r3/ops/supervisor_contract_test.py`,
  SHA-256 `5d9ba43aab398412e1fbad103b2ed2e18476e1dc07a500e64b415c93dc21e3c1`;
- frozen H0 group split SHA-256
  `fa704103e39cd2259d20800608a75bd4d1b64b1dacfe62cdd85eeeae916e25be`;
- real-host plan receipt
  `/opt/belief-v1-v2-freeze-15cc-r3/plan-summary.json`, SHA-256
  `9ca0ef6d9773d49ce58c8b943f6807868ee0d34233c0db4f8f38e689832fa0f8`.

From `/opt/belief-v1-v2-freeze-15cc-r3/ops`, run:

`python3 -B supervisor_contract_test.py`

`./supervisor.py --validate-plan-only`

Require all of the following in this same review:

- each of exactly 30 source files is byte-hashed into
  `sha256("belief-v1-v2-human-source-group-v1|" + source_sha256)` and maps
  exactly once into the canonical disjoint 24 train / 3 calibration / 3 test
  split;
- exactly 9 human-reference tasks: calibration replicate 0 ×3, calibration
  replicate 1 ×3, test-primary ×3, and zero train references;
- the old 90-task Cartesian matrix, an added train reference, a wrong
  calibration replicate, a dropped required replicate, duplicate/missing
  digest, wrong split counts, and extra source all fail in the tests;
- the entire unique 80-task plan is validated before `started.json` can be
  created;
- stage order and concurrency are exactly:
  synthetic capture 16 → human capture 16 → training index 1 → device
  qualification 1 → all references 16 → training 4 → calibration 1 → sole
  test open 1 → terminal verification 1;
- all references therefore seal before training begins; first nonzero exit is
  fail-fast with no retry;
- plan-only hashes source bytes but parses zero source records/outcome fields,
  publishes no source/outcome values, and creates no ops/evidence state.

This supervisor is external orchestration only. Scientific source remains the
already-reviewed clean detached PR #119 head
`15cc8f83ef736705fc9170b7f84eb169663785e3`, authenticated by source PASS
`f952667d77da1c2e597915f19c5931fb545cdfdf`.

### 3. Reopen fresh R3 freeze and exact claim

- design `/opt/belief-v1-v2-design-15cc-r3.json`, root-owned 0400,
  SHA-256 `fbd1fa21ec3671757c59e68b3b95efa8d41c59e63961c1bdc73801c1445d2c2c`;
- consolidated packet
  `/opt/belief-v1-v2-freeze-15cc-r3/review-packet.json`, SHA-256
  `845a887166ef633d1f106409c08566eb4762af9cfa9d6ef4a97e3e424658c3fe`;
- independently compare R2 freeze
  `a6cc38c8d7e21c42f719d932ca35073474ca31becbcb8598eadabe8afcddc2a9`
  with R3: the sole decoded difference must be evidence root
  `/opt/belief-v1-v2-evidence-15cc-r2` →
  `/opt/belief-v1-v2-evidence-15cc-r3`;
- verify R3 evidence root, started/status files, and workers remain absent;
- regenerate `expected_execution_review_claim(freeze)` and require byte
  identity with
  `/opt/belief-v1-v2-freeze-15cc-r3/expected-review-claim.json`, SHA-256
  `4b81e4def9e4f0dfc4d288c6be93885aa4573c73e0e8e437134172d84f98ded8`.

The first freeze invocation refused `V2 runtime environment drift` before
creating a design or evidence root; its bound stderr is disclosed in the
packet. The successful freeze used the exact required environment. This is not
an execution attempt.

### Required verdict and marker

Return one consolidated `PASS` or `HOLD`, findings ordered by severity, and
explicitly state whether R2 opened any scientific/test result, whether the
split/task mutations were killed, whether R2→R3 has only the evidence-root
delta, whether the claim regenerated byte-exactly, and whether Codex may
initialize and execute only this one bounded R3 DAG.

On PASS, append exactly one machine-generated marker at column 1 to
`HANDOFF_REVIEW.md` in one authenticated Claude-authored canonical-main
commit:

`BELIEF_V1_V2_OFFLINE_EXECUTION_V1_REVIEW {"bounded_capture_reference_training_and_one_test_open_authorized":true,"deadline_estimate_receipt_sha256":"2144d83765c17d42ded2c3fad44df7a5072d47da152e9b118cbad1cac7ccc0cc","deployment_authorized":false,"device_qualification_protocol_sha256":"79ec7e55b690294e082ea90e9edbe3f81168cb2a7d1bd03b27e8dca1078de2d0","evidence_root":"/opt/belief-v1-v2-evidence-15cc-r3","execution_git":"15cc8f83ef736705fc9170b7f84eb169663785e3","freeze_sha256":"fbd1fa21ec3671757c59e68b3b95efa8d41c59e63961c1bdc73801c1445d2c2c","gameplay_strength_screen_authorized":false,"promotion_authorized":false,"protocol_sha256":"a45903a79a9302c61201b428b01a97b7e9bf34d2c5b5478618331e1ce1a13b03","resource_caps_sha256":"2fe570f088e7d8c0aa5cd7bbf85e285d6acfcc53542639edb18eb0eaba2ec552","retry_authorized":false,"run_id":"belief-v1-v2-all-ranks-human-offline-v1","runtime_profile_sha256":"5c28d70d4f4edf3d28e10a328d3b5ca04c0aa812c6a99e333fac2bc8b85c9016","sampler_implementation_authorized":false,"schedule_sha256":"eea7d9581ce32cbce2c138977c4d1acd21f987c2076820f32ab9ca5d470ee4b6","schema":"belief-v1-v2-offline-execution-review-v1","seed_registry_sha256":"507b8a5156d4b057c55c4849c42eb5e66a09b1c1f66364f88e8f3e563e4d7fac","source_manifest_sha256":"85b658d694a4b20781fcc6c764d8807b8ce5b423c0b989bbcdeec90f85367790","strength_claim_authorized":false,"training_candidate_device":"cpu","training_device_profile_sha256":"2f7edb58c08d831ccc390f8ff77bb4b73a19f57e2f940977d9563c952ab673e0","v1_resource_failure_receipt_sha256":"257fce06ed612a0acda356b5a55395b64a4402dc95f7461ead364c48dfa6b4a3","v1_terminal_route":"RESOURCE_FAILURE_REPAIRED_FOR_NEW_V2_FREEZE_REVIEW"}`

After that review commit, do not mutate canonical main until Codex reports R3
terminalized or refused.

## Operational truth

- Strength Cloud is idle; no V2 worker is running.
- R1 and R2 are spent, preserved, and forbidden as input to R3.
- R3 is frozen but not initialized; the new evidence root and start token are
  absent.
- PR #119 remains draft at the already-reviewed exact source head.
