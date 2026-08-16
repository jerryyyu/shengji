# Active Claude/Codex handoff

> Current queue only. Historical reviews belong in `HANDOFF_REVIEW.md` and Git
> history. A request not listed here is not active.

Last reconciled: 2026-08-16 17:34 EDT.

## Immediate objective

Obtain one final exact immutable-freeze PASS for BELIEF-V1 V2, then let Codex
initialize once and run the complete bounded DAG without intermediate reviews.
After launch, canonical main must remain unchanged until terminal/refusal
because every worker re-authenticates the admission's exact remote tip.

## Top/only Claude ask — exact freeze `27760181…14605`

Perform one consolidated read-only review on `shengji-cloud`. Do not initialize
the evidence namespace, start any population/reference/training stage, open
calibration/test, merge PR #119, deploy, or grant gameplay/strength authority.

Exact packet:

- source checkout `/opt/shengji-15cc-v1`, clean detached exact
  `15cc8f83ef736705fc9170b7f84eb169663785e3`;
- authenticated source/re-entry PASS commit
  `f952667d77da1c2e597915f19c5931fb545cdfdf`;
- design `/opt/belief-v1-v2-design-15cc-v1.json`, root-owned 0400,
  SHA-256 `277601816ae27557117fad722891e6bbc4160bb47c67d34edd7c2c2d6d414605`;
- receipt workspace `/opt/belief-v1-v2-freeze-15cc-v1`, all closed files
  root-owned 0400 and both directories root-owned 0700;
- proposed evidence root `/opt/belief-v1-v2-evidence-15cc-v1`: root,
  `.partial`, and `.consumed.json` all absent.

Reopen the design through `execution_freeze_from_bytes` and
`validate_execution_freeze`. Independently regenerate
`expected_execution_review_claim(freeze)` and require it byte-identical to
`/opt/belief-v1-v2-freeze-15cc-v1/expected-review-claim.json`, SHA-256
`074e871a9d4457be0e011f02eef4fc7c9470ce32c658e362a147d774d3f69547`.

### Bindings to verify in this same review

- source manifest `85b658d694a4b20781fcc6c764d8807b8ce5b423c0b989bbcdeec90f85367790`:
  146 files, exact Git bytes, no bytecode/loadable shadows;
- runtime `5c28d70d4f4edf3d28e10a328d3b5ca04c0aa812c6a99e333fac2bc8b85c9016`:
  16 CPUs, 30.6 GiB, exact host/boot/Python 3.14.4/Torch 2.13/NumPy 2.5.1,
  one-thread deterministic Torch, and active native extension SHA
  `ed25d3554e6dd6c136ff29ed05af684ad5d38492a811e23ccfcf4d94fa5f9d0f`;
- all-rank preflight `725983a2c012d20635e4dfba61e62c7ffd0d85294c626eff30e81ad5c84ea1de`:
  416/416 rounds, 16 lanes, all 13 ranks, zero retained production rows;
- deadline receipt `2144d83765c17d42ded2c3fad44df7a5072d47da152e9b118cbad1cac7ccc0cc`:
  416 capture, 32 REF-C with 16 workers, two repeatable training passes,
  CPU, zero retained rows/worlds/model state, test unopened;
- exact deadline pins: capture `17,376,448,387 ns`, REF-C
  `38,734,708,161 ns`, projected epoch `36,508,062,558,976 ns`, reserve
  `1,825,403,127,949 ns`; four epochs plus reserve = about 41.07h < 48h;
- caps `2fe570f088e7d8c0aa5cd7bbf85e285d6acfcc53542639edb18eb0eaba2ec552`:
  capture 64 core-hours/5h/16GiB, REF-C 40 core-hours/4h/16GiB,
  training 256 device-hours/48h/32GiB, host/device memory 24/12GiB;
- fresh scan `b4682e16c03c4d944bf0808eae1b64309b770d92af1696ede1ad553dbe87b6e2`
  and registry `507b8a5156d4b057c55c4849c42eb5e66a09b1c1f66364f88e8f3e563e4d7fac`:
  all candidates classified, 13,312 V2 seeds, zero collisions;
- H0 inventory `201ef84e…e12f`, split `fa704103…e25be`, 30 groups / 122
  complete rounds / 2,830 decisions, and immutable root-owned source snapshot
  `/opt/belief-v1-v2-human-source-13d`; raw identity/path/world key excluded;
- V1 failure receipt `257fce06…b4a3` and re-entry rationale
  `abfb7121…70e0` exact; no prior captured evidence enters this freeze;
- the unused `d577-v2` root/tombstone never existed, and the spent `13d`
  namespace plus both superseded packet workspaces remain preserved;
- retry, sampler, gameplay, strength, promotion, and deployment authority are
  false everywhere.

### Required verdict and marker

Return one consolidated answer:

1. `PASS` or `HOLD` for exact freeze `27760181…14605`;
2. all findings ordered by severity with exact artifact/path evidence;
3. whether the regenerated claim is byte-identical;
4. whether it is safe to initialize and execute only the bounded offline DAG.

On PASS, append exactly one machine-generated marker at column 1 to
`HANDOFF_REVIEW.md` in one authenticated Claude-authored canonical-main commit:

`BELIEF_V1_V2_OFFLINE_EXECUTION_V1_REVIEW {"bounded_capture_reference_training_and_one_test_open_authorized":true,"deadline_estimate_receipt_sha256":"2144d83765c17d42ded2c3fad44df7a5072d47da152e9b118cbad1cac7ccc0cc","deployment_authorized":false,"device_qualification_protocol_sha256":"79ec7e55b690294e082ea90e9edbe3f81168cb2a7d1bd03b27e8dca1078de2d0","evidence_root":"/opt/belief-v1-v2-evidence-15cc-v1","execution_git":"15cc8f83ef736705fc9170b7f84eb169663785e3","freeze_sha256":"277601816ae27557117fad722891e6bbc4160bb47c67d34edd7c2c2d6d414605","gameplay_strength_screen_authorized":false,"promotion_authorized":false,"protocol_sha256":"a45903a79a9302c61201b428b01a97b7e9bf34d2c5b5478618331e1ce1a13b03","resource_caps_sha256":"2fe570f088e7d8c0aa5cd7bbf85e285d6acfcc53542639edb18eb0eaba2ec552","retry_authorized":false,"run_id":"belief-v1-v2-all-ranks-human-offline-v1","runtime_profile_sha256":"5c28d70d4f4edf3d28e10a328d3b5ca04c0aa812c6a99e333fac2bc8b85c9016","sampler_implementation_authorized":false,"schedule_sha256":"eea7d9581ce32cbce2c138977c4d1acd21f987c2076820f32ab9ca5d470ee4b6","schema":"belief-v1-v2-offline-execution-review-v1","seed_registry_sha256":"507b8a5156d4b057c55c4849c42eb5e66a09b1c1f66364f88e8f3e563e4d7fac","source_manifest_sha256":"85b658d694a4b20781fcc6c764d8807b8ce5b423c0b989bbcdeec90f85367790","strength_claim_authorized":false,"training_candidate_device":"cpu","training_device_profile_sha256":"2f7edb58c08d831ccc390f8ff77bb4b73a19f57e2f940977d9563c952ab673e0","v1_resource_failure_receipt_sha256":"257fce06ed612a0acda356b5a55395b64a4402dc95f7461ead364c48dfa6b4a3","v1_terminal_route":"RESOURCE_FAILURE_REPAIRED_FOR_NEW_V2_FREEZE_REVIEW"}`

After that commit, do not mutate canonical main until Codex reports that the
pipeline terminalized or refused. No intermediate review is requested.

## Operational truth

- Performance Cloud is idle; no V2 population process is running.
- No admission or scientific namespace has been consumed for this packet.
- PR #119 remains draft and is not part of this review decision.
