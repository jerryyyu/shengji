# Active Claude/Codex handoff

Last compacted: 2026-08-09 18:05 EDT. This is the executable mailbox, not a
history. Terminal conclusions live in `AI_POLICIES.md`, live compute in
`JOBS.md`, queue order in `BACKLOG.md`, and durable review records in
`HANDOFF_REVIEW.md`.

## Current truth

| area | status | next legal action |
|---|---|---|
| Production | **LIVE / CONFIRMED** | Fly release 17 runs compiled `mc-s0-report-lcb`; RLCB-C1 measured `+0.338 +/- 0.068` signed levels versus `mc-strong`. |
| S3a structured bury | **TERMINAL SELECT NONE** | Structured-minus-champion was `+0.0464`, LCB `-0.0041`; aggregate `20609613…271f`, final `32156d79…c9ff`. No retry, tuning, confirmation or pooling. |
| S4 point banking | **2,048-CLUSTER MINI SCREEN RUNNING / SEALED** | Exact `cad3992`, packet `17036e63…1385`, admission `1d99bb55…bdbf`, receipt `20a420d2…5cc`. Count/status monitoring only, then one terminal verify. |
| Human H0 | **CONTROLLER V1 HOLD / ZERO OUTCOMES** | Claude found two launch-boundary defects: runtime did not itself enforce compiled/strict-void mode, and deleting the receipt could reissue admission. Preserve packet `13d9a97f…61fc`; freeze a separately versioned replacement before review. |
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
| **T3.4 H0 controller** | Identify which human/V11/random proposals survive fresh rollout evaluation and can seed better ballots or Teacher examples. | **V1 held before outcomes.** Repair strict runtime enforcement and deletion-proof admission, mutation-test both, then freeze v2. |
| **T3.5 Stage-C-v3 contract** | Spend expensive labels on uncertainty, disagreement, point play, bury and late states rather than ordinary heuristic self-play. | V2 binds obsolete H0. Rebind/freeze v3 after H0 controller PASS; no dataset exists yet. |
| **T3.6 S3c feasibility** | Start exact search at tiny natural endgames, then grow one card at a time instead of retrying the failed four-card jump. | **Controller packet frozen for review.** Focused gate is 49/49. PASS may authorize one mechanics/capacity run, not a strength screen. |
| **Human evaluation boundary** | Ensure a bot that beats bots can ultimately be tested honestly against people. | `human_v8` is provenance-verified and training-excluded. HUMAN-C1 traffic remains parked. |

## Sole active review — S3c one-card score-free capacity controller

### Plain-English review question

Does this controller faithfully turn the passed S3c curriculum into one finite
one-card mechanics/capacity experiment? Every selected root has exactly one
legal action. Review that the future runtime samples exactly four worlds per
root, invokes the exact continuation inside its node ceiling, publishes only
digests and capacity counters, and cannot silently retry a refused world. This
review must not sample a hidden world or invoke the solver.

### Exact assets and measured facts

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

### Load-bearing checks

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

1. Repair and version the H0 controller under Claude's 17:54 HOLD; freeze a
   new score-free packet. Do not execute counterfactual worlds.
2. Rebind/freeze Stage-C-v3 only after replacement H0 controller PASS.
3. Build the S5 score-free bot-decision replay census if coding capacity
   remains. Do not infer a treatment from aggregate human-loss forensics.

## Fleet and safety

- Mini: S4 screen only; read count/status heartbeats, never partial outcomes.
- Air: free for exact tests/reviews or another already reviewed job.
- Fly: production release 17; passive monitoring only.
- Never retry, resume, extend, tune from or pool a consumed one-shot stream.
- Never promote from diagnostics; fresh paired confirmation owns policy
  strength and the future blinded human ladder owns product value.
