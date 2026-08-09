# Active Claude/Codex handoff

Last compacted: 2026-08-09 18:24 EDT. This is the executable mailbox, not a
history. Terminal conclusions live in `AI_POLICIES.md`, live compute in
`JOBS.md`, queue order in `BACKLOG.md`, and durable review records in
`HANDOFF_REVIEW.md`.

## Current truth

| area | status | next legal action |
|---|---|---|
| Production | **LIVE / CONFIRMED** | Fly release 17 runs compiled `mc-s0-report-lcb`; RLCB-C1 measured `+0.338 +/- 0.068` signed levels versus `mc-strong`. |
| S3a structured bury | **TERMINAL SELECT NONE** | Structured-minus-champion was `+0.0464`, LCB `-0.0041`; aggregate `20609613…271f`, final `32156d79…c9ff`. No retry, tuning, confirmation or pooling. |
| S4 point banking | **2,048-CLUSTER MINI SCREEN RUNNING / SEALED** | Exact `cad3992`, packet `17036e63…1385`, admission `1d99bb55…bdbf`, receipt `20a420d2…5cc`. Count/status monitoring only, then one terminal verify. |
| Human H0 | **CONTROLLER V2 FROZEN / REVIEW OPEN / ZERO OUTCOMES** | V1 `13d9a97f…61fc` remains HOLD. Source `6977dbb`, asset `d99f7e8` and packet `3f68dc6e…7fcf` add runtime self-attestation plus deletion-proof one-shot admission. Review only; do not execute worlds. |
| Teacher Stage C | **T1 COMPLETE / V2 HELD** | Rebind the score-free design only after the replacement H0 controller passes. No state capture, labels, compute or training. |
| S3c small endgames | **ONE-CARD CONTROLLER FROZEN / REVIEW OPEN** | Source `e9db4a2`, asset `64dc65a`, packet `f58d23b7…3874`. The clean freeze replayed 64 public roots with zero sampled worlds and zero solver sessions. Review only. |
| S5 point protection | **REPLAY HYPOTHESIS ONLY** | Reconstruct bot-seat losing follows and prove an avoidable lower-point legal action exists before designing a treatment. |
| HUMAN-C1 | **PARKED / NO TRAFFIC** | Preserve the inert seam until a challenger beats report-LCB in confirmation. |

## Active milestone — T3 human-witness challenger readiness

Plain-English objective: turn human/model ideas and observed loss modes into
one honestly tested challenger while the reviewed S4 policy receives a real
whole-game test.

| output | why it can improve strength | progress and what remains |
|---|---|---|
| **T3.1 S3a verdict** | Test whether broader point/void/trump kitty choices improve the whole bot. | **Closed SELECT NONE.** The state-level signal did not survive the fresh full-game gate. |
| **T3.2 S4 whole-game screen** | Correct a rollout blind spot: a player already winning may bank a 5/10/K while retaining higher control. | Exact-state mechanism passed; the reviewed Mini screen is running sealed. |
| **T3.3 H0 bounded design** | Let human and V11 actions expand the bot's ideas, but judge them fairly instead of copying them. | **Closed design PASS** at `239f13c`; exact v3 packet `4d3f0a35…8cc3`. |
| **T3.4 H0 controller** | Identify which human/V11/random proposals survive fresh rollout evaluation and can seed better ballots or Teacher examples. | **V2 frozen / review open.** All 557 rows replayed score-free; strict runtime and durable one-shot admission are directly tested. External PASS/HOLD remains. |
| **T3.5 Stage-C-v3 contract** | Spend expensive labels on uncertainty, disagreement, point play, bury and late states rather than ordinary heuristic self-play. | V2 binds obsolete H0. Rebind/freeze v3 after H0 controller PASS; no dataset exists yet. |
| **T3.6 S3c feasibility** | Start exact search at tiny natural endgames, then grow one card at a time instead of retrying the failed four-card jump. | **Controller packet frozen for review.** Focused gate is 49/49. PASS may authorize one mechanics/capacity run, not a strength screen. |
| **Human evaluation boundary** | Ensure a bot that beats bots can ultimately be tested honestly against people. | `human_v8` is provenance-verified and training-excluded. HUMAN-C1 traffic remains parked. |

## Active reviews — priority order

### Review 1 — H0-v3 score-free controller v2

#### Plain-English review question

Does v2 close the two real launch defects without changing the reviewed H0
experiment? The future run must refuse unless compiled search and strict void
sampling are active, and consuming the durable admission slot must remain
irreversible even if receipt publication fails or someone later deletes the
receipt. This review must replay public decisions only; it must not sample a
world, score a candidate or execute H0.

#### Exact assets and measured facts

- source `6977dbbdc77276b115faf941509b8034d7801bf0`; asset commit `d99f7e8`;
- packet `server/runs/logs/human-v8-h0-counterfactual-controller-v2/controller_packet.json`;
- external/internal packet SHA-256 `3f68dc6ec6d5f90043f36c0a68847ca9ef510641e01760ac4fa11ebd6a6a7fcf` / `7744c745fd92f5ae725c8a2f45882b7e6668c14b5bf2a3570c738d245dc6b9ec`;
- controller/runtime SHA-256 `108e6bb2…379` / `ddf8b250…a124`;
- schedule/candidate geometry `f54ce374…793` / `876ed56b…ff2b`;
- compiled binary/router SHA-256 `9c9e77fb…e4c1` / `f2506d5c…1a3e`;
- all 557 public rows replayed; maximum future work remains 1,329,210
  candidate-world rollouts;
- focused H0 packet/controller tests pass 34/34; the broader H0 + Stage-C/B
  battery passes 58/58;
- real CLI probes refuse missing `SHENGJI_REQUIRE_VOIDS=1` and refuse
  `SHENGJI_UNIFORM_DEAL=1`, both with exit status 3;
- freeze/recompute sampled **0 worlds**, ran **0 candidate rollouts** and
  computed **0 outcomes**.

#### Load-bearing checks

1. Recompute the packet from clean source `6977dbb`; confirm all design,
   corpus, source-log, V11, live-parent, schedule and source hashes.
2. Confirm every runtime packet open—not only freeze—requires exact
   `SHENGJI_FAST=1` and `SHENGJI_REQUIRE_VOIDS=1`, compiled routing and no
   experimental sampler/ballot flag.
3. Mutation-test the durable slot
   `server/runs/locks/human-v8-h0-counterfactual-execution-v2.consumed.json`:
   it publishes before the receipt; deleting the receipt cannot reissue; a
   receipt-publication failure leaves the slot consumed.
4. Confirm v2 preserves H0-v3's 17/33 caps, three disjoint folds, proposal
   semantics, continuation, exact-work/refusal accounting and terminal replay.
5. Confirm PASS authorizes one future diagnostic receipt only. It authorizes no
   current execution, label, training, strength claim, promotion or deployment.

Requested marker:

`H0_HUMAN_COUNTERFACTUAL_CONTROLLER_V2_REVIEW {"admission_slot_logical_path":"server/runs/locks/human-v8-h0-counterfactual-execution-v2.consumed.json","candidate_geometry_sha256":"876ed56bd8f436d58cb6f3d58774a0f06756afb4d8c98ffdb49d9424b545ff2b","compiled_fast_binary_sha256":"9c9e77fbdc4c6caceec195465155f37ec6369e409462fd838bc142bf8a0be4c1","controller_script_sha256":"108e6bb20983350db2a7b679cd080f29acf6128fa0557d4d0e7f1a1823eaf379","corpus_manifest_sha256":"b9699790bdfe1c217922c9f9c72b237c1856174fa64c11753329a8ff11e16553","deletion_proof_one_shot":true,"design_packet_sha256":"4d3f0a35082c6957f2a468686b8eedbd6d7cbbf9540503fcea08cccf27c8cc3c","design_review_git":"239f13ce52a8be81108fdebf9bd0e96742e60133","fast_router_sha256":"f2506d5c51b8ad37303f04dce59899de0d7c1179633b08ce61f48eb86cec1a3e","git":"6977dbbdc77276b115faf941509b8034d7801bf0","independent_review":true,"labels_authorized":false,"max_candidate_worlds":1329210,"one_counterfactual_execution_authorized":true,"outcomes_computed_before_review":false,"packet_sha256":"3f68dc6ec6d5f90043f36c0a68847ca9ef510641e01760ac4fa11ebd6a6a7fcf","production_deployment":false,"production_promotion":false,"runtime_script_sha256":"ddf8b2504ff70d7af928e3c6f39c5a9e5071abd8eaea0c6af9c6719c2992a124","schedule_sha256":"f54ce37425707dfeea3563bbc5d635617943152166a82825a74e55ad00131793","schema":"human-h0-counterfactual-controller-review-v2","score_free_preflight_verified":true,"selected_bury_rows_sha256":"cdfe77dfbec0e97fb8935c5822239acd6db60c644c433c32a4445913459aa1e8","selected_play_rows_sha256":"18673b20ca0a5b1a8e476f3bcf45cf9d08f90f4244f9c5ee07cb8bd8cd47711d","source_manifest_sha256":"07ff18fb35f2fb987f18b37b5100172e2751681fbfed17285ce7d7035232aa5e","strength_claim":false,"strict_runtime_verified":true,"training_authorized":false,"v11_checkpoint_sha256":"cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003","verdict":"PASS","worlds_sampled_before_review":0}`

Append PASS/HOLD and measured findings only to `HANDOFF_REVIEW.md`. A PASS
unblocks Stage-C-v3 rebinding and makes one later T4 H0 diagnostic execution
eligible; it does not launch either.

### Review 2 — S3c one-card score-free capacity controller

#### Plain-English review question

Does this controller faithfully turn the passed S3c curriculum into one finite
one-card mechanics/capacity experiment? Every selected root has exactly one
legal action. Review that the future runtime samples exactly four worlds per
root, invokes the exact continuation inside its node ceiling, publishes only
digests and capacity counters, and cannot silently retry a refused world. This
review must not sample a hidden world or invoke the solver.

#### Exact assets and measured facts

- producer source `e9db4a23457ff4221d342c9a422e50ea491fe7ab`;
- asset commit `64dc65a`;
- packet `server/runs/logs/s3c-one-card-capacity-controller-v1/controller_packet.json`;
- external/internal packet SHA-256 `f58d23b74046dd04963b4f10fbf605030221219eef6d325c5e8319043643874a` / `7c6563d4110dc37af3c2d4fe8bf32f38041bdae10ee0e0c216b22d8c2cbf7104`;
- controller/runtime SHA-256 `9f3cf108…468eb` / `5886fecf…33c2`;
- schedule/root geometry `8257499b…e7de` / `b2599bb5…be0b`;
- parent design/census `df102428…9eca` / `23632609…b52a`;
- 64 roots: 16 per within-trick offset, 27 attacker / 37 defender, 16 lead / 48 follow;
- 256 unique deterministic world seeds; maximum 65,536 execution nodes plus
  65,536 terminal-replay nodes;
- focused controller/design/endgame tests pass 49/49;
- freeze and full recomputation both return
  `VERIFIED_FOR_CONTROLLER_REVIEW` with **0 worlds**, **0 exact sessions** and
  no action value, outcome or execution authority.

#### Load-bearing checks

1. Recompute design/census/source/native identities, root selection, all world
   seeds, schedule, score-free geometry and both packet hashes.
2. Confirm freeze/verify replay only public roots: no `Memory`, sampler,
   determinization or exact solver call may occur before review.
3. Check one accepted world creates exactly one exact session. Offsets 0–2
   must open one exact frontier; offset 3 opens none because the forced play
   terminates the round.
4. Mutation-test sampler refusal, exact refusal and node overflow. Stop the
   root at its first refusal with no replacement/retry; publish counters and
   digests but no cards, points, values, utility, estimand or winner.
5. Check the durable admission slot publishes before the receipt, so deleting
   the receipt cannot reissue the run.
6. Check terminal verification replays every public root and every COMPLETE
   root's worlds once, never retries refused worlds, and stays below its
   separate 65,536-node replay ceiling.
7. Confirm a complete terminal can authorize only review of a future two-card
   mechanism packet—not a solver/strength screen, training or production.

Pinned focused command:

```sh
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 PYTHONPATH=server /Users/jerryyu/Projects/shengji/server/.venv/bin/python -m pytest -q server/tests/test_s3c_one_card_controller.py server/tests/test_s3c_exact_root_design.py server/tests/test_endgame.py
```

Run the controller's `verify` command from clean exact producer `e9db4a2`
against the tracked asset. It must report 64 replayed roots, zero sampled
worlds, zero exact sessions and no execution authority.

Requested marker:

`S3C_ONE_CARD_CAPACITY_CONTROLLER_V1_REVIEW {"census_sha256":"236326099dc9763c6a5941bcb2a90670c4e23ac390ea07a0e4ec5063fa50b52a","controller_script_sha256":"9f3cf108bf5f0706080a9f270f2c756f91c9b8cc6ed46cff53fa5b028d0468eb","design_packet_sha256":"df1024280a77c60174a57c3273ba3624e672bec9afde023576fde0404df49eca","design_review_git":"084ba7eba59cd0a317a50c4088f194d2376c1e03","exact_solver_sessions_before_review":0,"git":"e9db4a23457ff4221d342c9a422e50ea491fe7ab","independent_review":true,"max_execution_nodes":65536,"max_terminal_replay_nodes":65536,"one_card_capacity_execution_authorized":true,"outcomes_computed_before_review":false,"packet_sha256":"f58d23b74046dd04963b4f10fbf605030221219eef6d325c5e8319043643874a","production_deployment":false,"production_promotion":false,"root_geometry_sha256":"b2599bb50d8e2bd2762ac73af3206749e1f446eb5b971c1562e706883e48be0b","roots":64,"runtime_script_sha256":"5886fecfb11020d6b32488076e12356a02874499f2a42024d24fdf60fb4233c2","schedule_sha256":"8257499b8b613d02c899161bfd8ffac5579336dc54239ab443dfe5a7fad5e7de","schema":"s3c-one-card-capacity-controller-review-v1","score_free_preflight_verified":true,"solver_or_strength_screen_authorized":false,"strength_claim":false,"training_authorized":false,"two_card_packet_review_authorized":false,"verdict":"PASS","worlds":256,"worlds_sampled_before_review":0}`

Append PASS/HOLD and measured findings only to `HANDOFF_REVIEW.md`. A PASS
authorizes creation of one mechanics/capacity receipt. It does not itself run
the experiment or authorize two-card work, strength, training or production.

## Queued implementation while review/compute runs

1. Rebind/freeze Stage-C-v3 only after H0 controller-v2 PASS.
2. Build the S5 score-free bot-decision replay census if coding capacity
   remains. Do not infer a treatment from aggregate human-loss forensics.

## Fleet and safety

- Mini: S4 screen only; latest count-only heartbeat is 270/2,048 with all eight
  workers live. Never inspect partial outcomes.
- Air: free for exact tests/reviews or another already reviewed job.
- Fly: production release 17; passive monitoring only.
- Never retry, resume, extend, tune from or pool a consumed one-shot stream.
- Never promote from diagnostics; fresh paired confirmation owns policy
  strength and the future blinded human ladder owns product value.
