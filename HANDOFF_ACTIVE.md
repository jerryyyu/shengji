# Active Claude/Codex handoff

Last update: 2026-08-07 12:00 EDT. This file is the executable mailbox only.
The exact pre-compaction packet is recoverable at commit `ca556c2`; durable
discussion and retractions remain in `HANDOFF_REVIEW.md`.

## Current truth

- **Production:** Jerry manually approved and Codex deployed compiled
  `mc-s0-report-lcb`. Commit `74be565`, Fly version 16, machine check passing;
  `/healthz` returns `{"bot":"mc-s0-report-lcb","fast":true}`.
  `mc-strong` is the immediate rollback. This is a product decision based on
  replicated S0a/b development evidence, not a formal S0 promotion.
- **S0 formal milestone:** COMPLETE / `S0_COMPLETE_SELECT_NONE`, because the
  evidence pipeline burned before corrected outcome parsing. Do **not** call
  this a negative game result.
- **S0 process state:** the eight inert S0c services were booted out after exact
  namespace/PID verification. `com.shengji.s0mini.*` is empty; no evidence or
  attempt file was deleted. Mini is free.
- **DEV-512:** SELECT NONE / closed. CALIB and REPORT remain sealed.
- **V11 direct-v2:** game compute is complete; artifact publication is blocked
  by a false validator assumption that house utility is capped at `+/-1..3`.
  Repair from existing bytes only; do not replay games.
- **Teacher 143M-v2:** capture completed, then refused before diagnostics when
  the v11 actor emitted an off-ballot noncanonical action. Preserve the failed
  namespace and version the repair.
- **Next admitted Mini compute:** six Direct-Q 32-iteration score-redacted
  preflights, not the full 512-iteration screen.

## S0 terminal return packet

```text
STATE:
  S0_COMPLETE_SELECT_NONE
  Administrative outcome-blind closeout; no S0c outcome parsed.

HEAD / origin / dirty:
  ca556c2 / ca556c2 / clean at terminal verification

S0a:
  8/8 x 256 clusters, exact 132M block
  survivor = mc-s0-report-lcb
  aggregate SHA = 0fcd53d4f782a705bfef9ea8ec6155c49db45d76ec71ce25891a9f864413de49
  report-LCB-current = +0.353 +/- 0.069
  report-LCB-equal-work-uniform = +0.293 +/- 0.066
  null-current = +0.008 +/- 0.070

S0b:
  8/8 x 256 clusters, exact 134M block
  registered survivor = mc-s0-adaptive
  aggregate SHA = 25c0177e27c0e185e96701ad788313a7ea14b892e24586186df02466bf144803
  adaptive-report-uniform = +0.037 +/- 0.060
  adaptive-random = +0.433 +/- 0.065
  report-uniform-current = +0.357 +/- 0.066
  adaptive-current = +0.395 +/- 0.067
  null-current = +0.008 +/- 0.067
  interpretation: report-LCB replicated; adaptive increment unresolved

S0c:
  8/8 x 1,024 clusters and frozen aggregate completed on exact 135M block
  packet SHA = e03ed8b6e94e4f622e6033513443263f0887b0bb9163c68edfe49f33e508617b
  aggregate SHA = 4624d70c307f774f46c447b3e5456a5578d50e526b83be49cca5ea595e84cc00
  effects / counters / promotion criteria = NOT PARSED / NOT REPORTED
  reason: one-shot corrected evaluator refused before outcome decoding
  no retry, pooling, extension, alternate split or inspection is authorized

Dependency authority:
  seal attempt SHA =
    3da45785a7b7032785573bae4f1ba2e3b740f726d29e5e6efb46021511e3c1f8
  input seal SHA =
    b6a48e9dbabad008a15e3ace0b19fecff9304849435b5d9c4f69da30ddc29d10
  exact 18-input-set SHA =
    14a74a76b14bc6fd731f3de5cf332ee50060c18f7baba1ad77614766e35b1361
  evaluation attempt SHA =
    97d3b22f656f9b43a8b34acf4085896706bb40b48c88f3b095cb08592725f9c5
  evaluation outcomes_parsed = false
  blocked supervisor-state SHA =
    ed80b0e18c5d843354271fb17554cda447b85f103a4def23f74b41c2bfcff378
  per-color corrected effects = NOT REACHED

Outcome-blind closeout:
  code commit = 17f4085362ad692fea8e558fde240fb8843f44d9
  attempt SHA =
    6104cbab343e29fcf1cc20ec0280b14374c88cb9a78bef169cf37e458a044ca5
  output SHA =
    ef0a3659859b38d0b9362376e5e403fecb625f59c475600ed09906ce695fde9a
  outcomes_parsed = false
  outcome_records_decoded = false
  promotion_admissible = false
  retry_or_extension_authorized = false

S0e-v2 terminal parent:
  commit = ca556c2
  transition = TERMINAL
  authorized = false
  final state = S0_COMPLETE_SELECT_NONE
  dependency audit SHA = ef0a3659859b38d0b9362376e5e403fecb625f59c475600ed09906ce695fde9a

CALIB / REPORT:
  sealed and unscored
```

The parent lock's frozen formal phrase “production remains mc-strong” records
what S0 itself was allowed to authorize. It does not describe or revoke Jerry's
separate manual report-LCB production decision.

## Work queue and exact gates

1. **V11-v2 artifact-only repair**
   - Preserve the seven normal terminal shards, shard-5 `.FAILED`, all raw
     bytes and the original failed namespace.
   - Replace the invalid `abs(utility)<=3` consumer assumption with uncapped
     integer validation recomputed from the retained engine result.
   - Reopen exact source/checkpoint/encoder/ballot/runtime/seed/flip/dose and
     sampler counters; publish to a new exclusive namespace.
   - Bind the original failure. Never replay a game, rewrite the stored verdict,
     or claim model activation that the runner did not record.
   - The draft in `/private/tmp/shengji-v11-v2-repair` is HOLD: recursion bug,
     untracked script, no committed tests.

2. **Teacher actor/gate v3**
   - Preserve refused `teacher-v1-entry-143m-v2`.
   - Canonicalize v11 lead actions and sorted follow actions to its ballot;
     return `actions[0]` when the ballot has one action.
   - Pin the named failing witness (seed 143000001, ply 44, seat 0), both roles,
     and a broader zero-off-ballot actor scan. Claude's scratch measured 0/872
     only after this fix; turn that into a falsifying test.
   - Version a fresh packet/output namespace. Run capture -> diagnostics ->
     exact 64-state freeze only, then stop for review.

3. **Direct-Q preflights on Mini**
   - Run only the six frozen 32-iteration treatment/no-step preflights from the
     accepted exact code identity.
   - Inspect wall/storage and semantic receipts, not a favourable score tail.
   - Full 512-iteration execution requires the predeclared admission result.

4. **Fresh report-LCB formal confirmation**
   - New version, new collision-free null, fresh deal block, exact
     report-LCB/current/null only.
   - Bind accepted dose, counters, runtime and one immutable superiority gate.
   - Do not reuse 135M, inspect S0c, or add adaptive allocation to this question.

5. **Reparent dependent strength lanes**
   - Protected V11, structured bury and sampled-exact endgame were frozen before
     production changed.
   - Explicitly name either formal `mc-strong` or live report-LCB as reference;
     for product strength, report-LCB is the relevant bar.
   - Version the parent and matched null/work contracts before any run.

## Message to Claude

Please audit commits `17f4085` and `ca556c2` plus the compacted docs. The
specific review question is whether the refusal closeout/terminal lock can
possibly decode, promote, retry or authorize a dependent experiment; do not
open any sealed S0c outcome while reviewing.

After that, the highest-value bounded implementation is the V11-v2 artifact-only
repair, followed by the teacher actor/gate v3 canonicalization. Post exact
commit/tests/artifact paths and any HOLD here. Do not duplicate Direct-Q
preflights or start a teacher capture until ownership is explicitly recorded.

## Standing rules

- Every accepted commit is pushed.
- Never delete or overwrite failed/evidence namespaces.
- Screens select; only fresh paired confirmations can establish strength.
- Partial/live outcomes do not drive code, stopping or sample-size changes.
- House progression is uncapped; clipped `+/-3` utility is a named legacy RL
  target only.
- Production policy changes are separate reviewed actions; formal experiment
  locks do not silently deploy or roll back a bot.
