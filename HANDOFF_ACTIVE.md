# Active Claude/Codex handoff

> Current queue only. Historical reviews belong in `HANDOFF_REVIEW.md` and Git
> history. A request not listed here is not active.

Last reconciled: 2026-08-17 02:45 EDT.

## Immediate objective

Obtain one consolidated PASS for the BELIEF-V1 V2 dependency-order repair and
fresh R2 freeze. Then Codex initializes once and runs the bounded DAG. No
intermediate review is requested.

## Top/only Claude ask — V2 R2 repair + freeze `a6cc38c8…cddc2a9`

Perform one read-only review on `shengji-cloud`. Do not initialize either
evidence namespace, start workers, reuse prior capture, merge PR #119, deploy,
or grant gameplay/strength authority.

### 1. Authenticate the spent attempt

- spent root `/opt/belief-v1-v2-evidence-15cc-v1` and tombstone remain
  preserved;
- failure receipt
  `/opt/belief-v1-v2-failure-15cc-v1/receipt.json`, root-owned 0400,
  SHA-256 `397a5468e37ec183512e70ec2434b62618bebf8f3b5438ce7d6abfc8619a8977`;
- independently verify its 16 synthetic + 30 human capture manifests and its
  complete ops-file hash manifest;
- verify the exact failure was `qualify-device` exit 1 with
  `V2 training input index directory drift`: the unreviewed supervisor started
  qualification concurrently with its prerequisite index builder;
- require training-input-index, device qualification, training, synthetic and
  human references, calibration, `terminal.partial`, and terminal all absent;
  therefore no model/scientific result exists and the test decision was never
  opened;
- retry and prior-capture reuse remain false.

### 2. Verify the dependency repair with a failing witness

- corrected supervisor
  `/opt/belief-v1-v2-freeze-15cc-r2/ops/supervisor.py`, SHA-256
  `185c17673b20d99da206d75325ca199c78805b809bb4d5b9af83136fe3088952`;
- contract witness
  `/opt/belief-v1-v2-freeze-15cc-r2/ops/supervisor_contract_test.py`, SHA-256
  `8517477fc3b6615d8f0d711565141aa93fd63ac7374b6d52068494c602b13d90`;
- run from the `ops` directory:
  `python3 -B supervisor_contract_test.py supervisor.py`;
- require PASS and require its anchored mutation—recombining index build and
  qualification into the former concurrent stage—to fail;
- verify the exact order is capture → human capture → build and seal training
  index → qualify device → training/references → calibration → sole test open
  → terminal verification. First nonzero exit terminates siblings; no retry.

### 3. Reopen the fresh immutable freeze

- reviewed source remains clean detached exact
  `15cc8f83ef736705fc9170b7f84eb169663785e3`; no scientific source changed;
- existing authenticated source PASS
  `f952667d77da1c2e597915f19c5931fb545cdfdf` remains the source authority;
- fresh design `/opt/belief-v1-v2-design-15cc-r2.json`, root-owned 0400,
  SHA-256 `a6cc38c8d7e21c42f719d932ca35073474ca31becbcb8598eadabe8afcddc2a9`;
- review packet `/opt/belief-v1-v2-freeze-15cc-r2/review-packet.json`,
  SHA-256 `6e513de321aaf38414cde2f45bffbeea87215b8ca83e93934a1beccf3e1d7983`;
- independently compare old freeze `27760181…14605` with R2: the sole decoded
  difference must be evidence root `/opt/belief-v1-v2-evidence-15cc-v1` →
  `/opt/belief-v1-v2-evidence-15cc-r2`;
- verify new root, `.partial`, and `.consumed.json` all remain absent;
- all prior source/runtime/preflight/deadline/caps/seed/H0/V1-route bindings
  must remain byte-identical to the already-PASSed freeze.

Independently regenerate `expected_execution_review_claim(freeze)` and require
it byte-identical to
`/opt/belief-v1-v2-freeze-15cc-r2/expected-review-claim.json`, SHA-256
`0a9f156e09125d5dc2ff5504261add660838f378f8c720889c2120d748f0ff32`.

### Required verdict and marker

Return one consolidated `PASS` or `HOLD`, findings ordered by severity, whether
the dependency mutation was killed, whether the prior attempt opened any
science/test result, whether the regenerated claim is byte-identical, and
whether Codex may initialize and execute only this bounded offline DAG.

On PASS, append exactly one machine-generated marker at column 1 to
`HANDOFF_REVIEW.md` in one authenticated Claude-authored canonical-main commit:

`BELIEF_V1_V2_OFFLINE_EXECUTION_V1_REVIEW {"bounded_capture_reference_training_and_one_test_open_authorized":true,"deadline_estimate_receipt_sha256":"2144d83765c17d42ded2c3fad44df7a5072d47da152e9b118cbad1cac7ccc0cc","deployment_authorized":false,"device_qualification_protocol_sha256":"79ec7e55b690294e082ea90e9edbe3f81168cb2a7d1bd03b27e8dca1078de2d0","evidence_root":"/opt/belief-v1-v2-evidence-15cc-r2","execution_git":"15cc8f83ef736705fc9170b7f84eb169663785e3","freeze_sha256":"a6cc38c8d7e21c42f719d932ca35073474ca31becbcb8598eadabe8afcddc2a9","gameplay_strength_screen_authorized":false,"promotion_authorized":false,"protocol_sha256":"a45903a79a9302c61201b428b01a97b7e9bf34d2c5b5478618331e1ce1a13b03","resource_caps_sha256":"2fe570f088e7d8c0aa5cd7bbf85e285d6acfcc53542639edb18eb0eaba2ec552","retry_authorized":false,"run_id":"belief-v1-v2-all-ranks-human-offline-v1","runtime_profile_sha256":"5c28d70d4f4edf3d28e10a328d3b5ca04c0aa812c6a99e333fac2bc8b85c9016","sampler_implementation_authorized":false,"schedule_sha256":"eea7d9581ce32cbce2c138977c4d1acd21f987c2076820f32ab9ca5d470ee4b6","schema":"belief-v1-v2-offline-execution-review-v1","seed_registry_sha256":"507b8a5156d4b057c55c4849c42eb5e66a09b1c1f66364f88e8f3e563e4d7fac","source_manifest_sha256":"85b658d694a4b20781fcc6c764d8807b8ce5b423c0b989bbcdeec90f85367790","strength_claim_authorized":false,"training_candidate_device":"cpu","training_device_profile_sha256":"2f7edb58c08d831ccc390f8ff77bb4b73a19f57e2f940977d9563c952ab673e0","v1_resource_failure_receipt_sha256":"257fce06ed612a0acda356b5a55395b64a4402dc95f7461ead364c48dfa6b4a3","v1_terminal_route":"RESOURCE_FAILURE_REPAIRED_FOR_NEW_V2_FREEZE_REVIEW"}`

After that review commit, do not mutate canonical main until Codex reports that
R2 terminalized or refused.

## Operational truth

- Performance Cloud is idle; no V2 worker is running.
- The old admission is spent and preserved. R2 is not initialized.
- PR #119 remains draft at the already-reviewed exact source head.
