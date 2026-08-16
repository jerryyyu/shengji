# Active Claude/Codex handoff

> Current queue only. Historical reviews belong in `HANDOFF_REVIEW.md` and Git
> history. A request not listed here is not active.

Last reconciled: 2026-08-16 11:18 EDT.

## Immediate objective

Carry BELIEF-V1 V2 through exactly two remaining review boundaries:

1. this one immutable-freeze execution review; and
2. one terminal reconstruction review after the one-shot pipeline seals.

There are no per-stage capture, REF-C, index, qualification, cohort,
calibration, progress, or receipt reviews between them.

## Top/only Claude ask — exact immutable-freeze review

Read-only review on SSH host `shengji-cloud`. Do not initialize, execute,
rewrite, chmod, merge, deploy, open calibration/test, or create gameplay or
strength authority.

Review exact root-owned freeze `/opt/belief-v1-v2-design-13d-v1.json`, SHA-256
`9b75ac20413e3205bcfd8b5b06a55018f5bf4c635b0772e1f9afa740350daed6`.
Execution source is exact PR #119 head
`13d15c777cabcb7dd56316988e6b3c83f6a57d1c`; source PASS is canonical ledger
commit `f7c34b7600e2204f90c642b903a887a0c2ce9278`.

Reopen independently and verify:

- exact clean source/native/Python/Torch/Numpy/host/boot/runtime binding;
- 416-round all-rank preflight
  `/opt/belief-v1-v2-freeze-13d/preflight.json`, SHA
  `6e0bee49658f0156f93491c07acbdb3995e81e00f95a2739c6a8be532e826661`;
- deadline receipt
  `/opt/belief-v1-v2-freeze-13d/deadline-attempt2/deadline-estimate.json`, SHA
  `96e8f0e1a64e6242cb863e0bd33b08e10d9f5e914d4add158f56dd515dc03c69`:
  416 capture samples, 32 REF-C samples, two repeatable training estimates,
  retained rows/worlds/models/losses false, all authorities false;
- exact H0 inventory `201ef84e…e12f`, split `fa704103…25be`, V1 resource
  failure `257fce06…b4a3`, rationale `abfb7121…70e0`, scan
  `277f5a48…d961`, and registry `2a8da1e0…b3ae`;
- resource caps `/opt/belief-v1-v2-freeze-13d/inputs/resource-caps.json`, SHA
  `b6fa0b291ff6a9dae58f12d1a42916577f5a7af8704b1540bd50e36ba3202a20`,
  against derivation receipt SHA `09782017…82f`: capture 64 core-hours/5
  wall-hours/16 GiB; reference 40 core-hours/4 wall-hours/16 GiB; training
  256 aggregate device-hours/48 wall-hours/32 GiB; 24/12 GiB host/device
  memory. Confirm four p95 epochs plus reserve fit in 48 hours, making the
  patience-3 stopping rule evaluable;
- four exact cohort plans, CPU candidate/profile, qualification protocol,
  schedule/protocol/source hashes, unused sibling evidence root
  `/opt/belief-v1-v2-evidence-13d-v1`, retry false, and every downstream
  gameplay/strength/promotion/deployment authority false.

Operational audit note: three pre-design refusals are preserved outside the
freeze/evidence root: one deadline invocation lacked two required environment
literals and produced no receipt; freeze attempt 1 used a nonsibling output;
freeze attempt 2 found stale local `origin/main`. Each refused before its
target artifact. The successful deadline used a fresh directory, and the
successful freeze is the only design file. Confirm no evidence root exists.

Return PASS or HOLD with exact file/field findings. On PASS, append the exact
marker below byte-for-byte to `HANDOFF_REVIEW.md` in an authenticated
Claude-authored canonical-main commit. That marker grants only the bounded
offline pipeline and sole test opening described by the freeze; it grants no
retry, sampler, gameplay, strength, promotion, or deployment authority.

```text
BELIEF_V1_V2_OFFLINE_EXECUTION_V1_REVIEW {"bounded_capture_reference_training_and_one_test_open_authorized":true,"deadline_estimate_receipt_sha256":"96e8f0e1a64e6242cb863e0bd33b08e10d9f5e914d4add158f56dd515dc03c69","deployment_authorized":false,"device_qualification_protocol_sha256":"79ec7e55b690294e082ea90e9edbe3f81168cb2a7d1bd03b27e8dca1078de2d0","evidence_root":"/opt/belief-v1-v2-evidence-13d-v1","execution_git":"13d15c777cabcb7dd56316988e6b3c83f6a57d1c","freeze_sha256":"9b75ac20413e3205bcfd8b5b06a55018f5bf4c635b0772e1f9afa740350daed6","gameplay_strength_screen_authorized":false,"promotion_authorized":false,"protocol_sha256":"a45903a79a9302c61201b428b01a97b7e9bf34d2c5b5478618331e1ce1a13b03","resource_caps_sha256":"b6fa0b291ff6a9dae58f12d1a42916577f5a7af8704b1540bd50e36ba3202a20","retry_authorized":false,"run_id":"belief-v1-v2-all-ranks-human-offline-v1","runtime_profile_sha256":"616f732f3e8e713de8ff52f7819c4e6bb82926b94bdcfbbce180b48a00fce7fc","sampler_implementation_authorized":false,"schedule_sha256":"eea7d9581ce32cbce2c138977c4d1acd21f987c2076820f32ab9ca5d470ee4b6","schema":"belief-v1-v2-offline-execution-review-v1","seed_registry_sha256":"2a8da1e0d4575a5a9d252254b9c41d8896ee05fd93242993e46964df0b59b3ae","source_manifest_sha256":"1be7d826ff960277697a559edd832a5dd9df089a4cb8b4ebe1005fe1145a1c03","strength_claim_authorized":false,"training_candidate_device":"cpu","training_device_profile_sha256":"2f7edb58c08d831ccc390f8ff77bb4b73a19f57e2f940977d9563c952ab673e0","v1_resource_failure_receipt_sha256":"257fce06ed612a0acda356b5a55395b64a4402dc95f7461ead364c48dfa6b4a3","v1_terminal_route":"RESOURCE_FAILURE_REPAIRED_FOR_NEW_V2_FREEZE_REVIEW"}
```

## Operational truth and automatic next step

- PR #119 source review is closed PASS; do not re-review it.
- Both final-head measurements are complete and verified; no measurement job
  remains active.
- Freeze exists root-owned mode 0400; evidence root does not exist; pipeline
  has not started.
- The exact private H0 source population is already staged on `shengji-cloud`
  under root-only `/opt/belief-v1-v2-human-source-13d`: manifest
  `source-manifest.sha256` has SHA-256
  `07ff18fb35f2fb987f18b37b5100172e2751681fbfed17285ce7d7035232aa5e`;
  all 30/30 `.jsonl`
  members independently pass `sha256sum -c`, there are no extra members,
  files are root:root mode 0400 and both parent directories are mode 0700.
  The source path is not model input and no source bytes are published.
- PR #116 is Codex's separate performance item and does not block this review.
- After exact-freeze PASS, Codex authenticates the marker, initializes once,
  and runs the frozen single-host DAG with outcome-blind percentage telemetry.
  No further Claude review is requested until terminal bytes seal.

### Post-PASS execution DAG — automatic, no intermediate review

1. Fetch canonical main, authenticate the exact marker/commit, initialize the
   evidence root once, then `verify-root`. Any mismatch stops before work.
2. Run 16 synthetic capture lanes and 30 exact H0 group captures. Progress is
   fixed-unit and outcome-blind: rounds/4096 and human decisions/2830.
3. Build and reopen the immutable training-input index, then run the frozen CPU
   device qualification. A refusal stops; there is no alternate device or
   retry path.
4. Run 16 synthetic REF-C lanes plus the exact human calibration/test
   references (two replicates for the three calibration groups; one primary
   replicate for the three test groups). Progress reports completed reference
   units only, never scores.
5. Train the four frozen cohorts on CPU with the reviewed live deadline. Report
   epoch/unit percentage, elapsed time and remaining deadline only; do not
   inspect or publish losses, calibration, selection or model outcomes.
6. Seal calibration selection, then perform the sole test opening and terminal
   reconstruction. Any failure consumes the slot exactly as frozen; no retry.
7. Update this file to one terminal-review ask. Claude independently reopens
   the sealed bytes and appends the terminal verdict to `HANDOFF_REVIEW.md`.

Every stage uses exact source `13d15c7`, the external frozen Python/native
runtime, clean literal environment, root-owned inputs and the reviewed CLI.
The supervisor must stop on the first non-zero exit or missing expected
artifact. It may schedule independent stages concurrently only where the
reviewed DAG permits it and must not exceed the frozen CPU/memory/wall caps.
There is no ad hoc continuation, partial-result reading, retry, tuning or
additional review request.

## Durable references

- `BELIEF_V1_SPEC.md`, `BELIEF_V1_V2_DESIGN.md`
- `RL_PLAN.md`, `BACKLOG.md`, `AI_POLICIES.md`
- append-only authority ledger: `HANDOFF_REVIEW.md`
