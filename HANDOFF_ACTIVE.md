# Active Claude/Codex handoff

> Current queue only. Historical reviews belong in `HANDOFF_REVIEW.md` and Git
> history. A request not listed here is not active.

Last reconciled: 2026-08-16 16:36 EDT.

## Immediate objective

Obtain one exact immutable-freeze PASS for the repaired BELIEF-V1 V2 packet,
then let Codex initialize the fresh namespace and run the outcome-blind DAG.
There are no per-stage reviews. After this PASS, the only later review is the
terminal reconstruction/refusal review.

## Top/only Claude ask — exact freeze `495370a6…f7c17`

Read-only review on `shengji-cloud`. Do not initialize the evidence namespace,
start capture/REF-C/training, open calibration/test, reuse the spent admission,
merge PR #119, deploy, or grant gameplay/strength authority.

Exact packet:

- reviewed source checkout: `/opt/shengji-d577-v1`, clean detached
  `d57770b89236703e384e11c8b99b0a3691208627`;
- accepted source/re-entry ledger commit:
  `1172d033ce0bb22110232e7d81e2efd9da733a57`;
- immutable design: `/opt/belief-v1-v2-design-d577-v2.json`, root-owned 0400,
  SHA-256 `495370a60c9f6f0d40c1dfa45832d657080b1c9d1250bfd2e1441724e51f7c17`;
- fresh receipt workspace: `/opt/belief-v1-v2-freeze-d577-v1`, closed
  root-owned receipt population; compiler intermediates are outside it;
- proposed evidence root: `/opt/belief-v1-v2-evidence-d577-v2` — root,
  partial, and consumed tombstone are all absent.

Reopen the design through `execution_freeze_from_bytes` and
`validate_execution_freeze`, then independently regenerate
`expected_execution_review_claim(freeze)`. It must be byte-identical to
`/opt/belief-v1-v2-freeze-d577-v1/expected-review-claim.json` (SHA-256
`84193c28398764162fd7f566c4c43f12ce867377cab448b65ecd0845dd9a70cc`).

### Exact bindings to verify in the same review

- source manifest `3f3b22a1ad34a4cdc385e6d9d028ccab7790630f3e4a0433965d22c6e261b44c`:
  146 tracked files, exact Git head, clean tree, no bytecode/import shadows;
- runtime profile `9b314aeebf22f5d483b67d6e12b7b4d7758ae58159a77f1df1ea88e19752d3b0`:
  exact 16-CPU host/boot/Python/Torch/NumPy and active native extension
  `/opt/shengji-d577-v1/server/shengji/engine/_fast.cpython-314-x86_64-linux-gnu.so`
  SHA `35b11929ce3aaf449efe65b6874531821943ac402c21d3456d13ae230a2e5067`;
- fresh all-rank preflight `353f11245c6b8841783196e8ecfd59fca466a6131464d1e575d43034cbbb8d63`:
  exactly 416 rounds, 16 lanes, every trump rank 2..A, compiled+strict-voids,
  zero retained rows and all authority false;
- fresh deadline receipt `91c7f729a1849acc9b6e1ecac3a52fcf8ff8befa5731a33d0dc4fa413712e7cc`:
  416 capture samples, 32 REF-C samples with 16 workers, two training samples,
  identical semantic receipt hashes `faf6b241…e163`, device `cpu`, no retained
  rows/worlds/model state, production/test unopened, all authority false;
- measured p95 deadlines: capture `17,689,875,765 ns`, reference
  `38,306,397,080 ns`, training epoch `36,320,834,267,115 ns`, reserve
  `1,816,041,713,356 ns`; four p95 epochs plus reserve = 40.86h within the
  frozen 48h training wall;
- caps SHA `9542fa2d73f06acbf6cc9b26f424df213a82565bf5e0a4af8b28eb65bfee68e4`:
  capture 64 core-hours/5h/16GiB, reference 40 core-hours/4h/16GiB, training
  256 device-hours/48h/32GiB with 24GiB host and 12GiB device-memory caps;
- fresh seed scan `4a4d16e8cae79ba106c1afd707bc1a66831bef468dad7e7ffa9d0c171b3cbc45`
  and registry `44a3d35ddca6603cdc44e6bf24749e63a23c3130ba11f5705de0edaa84178749`:
  5,424 candidates classified, 13,312 V2 seeds, zero collisions, all
  registry authority false;
- H0 inventory `201ef84e…e12f`, group split `fa704103…e25be`, and immutable
  source snapshot `/opt/belief-v1-v2-human-source-13d`: 30/30 root-owned 0400
  source members pass the pinned manifest; these are frozen input bytes, not
  reuse of captured evidence;
- V1 failure receipt `257fce06…b4a3` and re-entry rationale
  `abfb7121…70e0` are byte-identical to the previously reviewed inputs;
- the spent V2 namespace `/opt/belief-v1-v2-evidence-13d-v1`, its tombstone,
  old design, and old ops logs remain preserved. No old capture byte enters the
  new freeze or future run.

### Required verdict and marker

Return exactly:

1. `PASS` or `HOLD` for design SHA `495370a6…f7c17`;
2. findings ordered by severity with exact artifact/path evidence;
3. whether the machine-regenerated claim is byte-identical;
4. whether it is safe to initialize and execute only this bounded offline DAG.

On PASS, append exactly one machine-generated marker at column 1 to
`HANDOFF_REVIEW.md` in one authenticated Claude-authored canonical-main
commit. The expected line is:

`BELIEF_V1_V2_OFFLINE_EXECUTION_V1_REVIEW {"bounded_capture_reference_training_and_one_test_open_authorized":true,"deadline_estimate_receipt_sha256":"91c7f729a1849acc9b6e1ecac3a52fcf8ff8befa5731a33d0dc4fa413712e7cc","deployment_authorized":false,"device_qualification_protocol_sha256":"79ec7e55b690294e082ea90e9edbe3f81168cb2a7d1bd03b27e8dca1078de2d0","evidence_root":"/opt/belief-v1-v2-evidence-d577-v2","execution_git":"d57770b89236703e384e11c8b99b0a3691208627","freeze_sha256":"495370a60c9f6f0d40c1dfa45832d657080b1c9d1250bfd2e1441724e51f7c17","gameplay_strength_screen_authorized":false,"promotion_authorized":false,"protocol_sha256":"a45903a79a9302c61201b428b01a97b7e9bf34d2c5b5478618331e1ce1a13b03","resource_caps_sha256":"9542fa2d73f06acbf6cc9b26f424df213a82565bf5e0a4af8b28eb65bfee68e4","retry_authorized":false,"run_id":"belief-v1-v2-all-ranks-human-offline-v1","runtime_profile_sha256":"9b314aeebf22f5d483b67d6e12b7b4d7758ae58159a77f1df1ea88e19752d3b0","sampler_implementation_authorized":false,"schedule_sha256":"eea7d9581ce32cbce2c138977c4d1acd21f987c2076820f32ab9ca5d470ee4b6","schema":"belief-v1-v2-offline-execution-review-v1","seed_registry_sha256":"44a3d35ddca6603cdc44e6bf24749e63a23c3130ba11f5705de0edaa84178749","source_manifest_sha256":"3f3b22a1ad34a4cdc385e6d9d028ccab7790630f3e4a0433965d22c6e261b44c","strength_claim_authorized":false,"training_candidate_device":"cpu","training_device_profile_sha256":"2f7edb58c08d831ccc390f8ff77bb4b73a19f57e2f940977d9563c952ab673e0","v1_resource_failure_receipt_sha256":"257fce06ed612a0acda356b5a55395b64a4402dc95f7461ead364c48dfa6b4a3","v1_terminal_route":"RESOURCE_FAILURE_REPAIRED_FOR_NEW_V2_FREEZE_REVIEW"}`

A PASS authorizes only the frozen capture/reference/training/calibration/sole
test-opening DAG. Retry, sampler, gameplay, strength, promotion, and deployment
authority remain false.

## Operational truth

- Performance Cloud is idle; both fresh measurement units completed
  `success/0`; no V2 process is running.
- PR #119 remains draft and is not part of this review decision.
- After exact-freeze PASS, Codex initializes once and launches the reviewed
  supervisor; progress is reported as completed/total percentages from the
  production worker. No stage-by-stage Claude round trip is required.

## Durable references

- `BELIEF_V1_SPEC.md`, `BELIEF_V1_V2_DESIGN.md`
- `RL_PLAN.md`, `BACKLOG.md`, `AI_POLICIES.md`
- append-only authority ledger: `HANDOFF_REVIEW.md`
