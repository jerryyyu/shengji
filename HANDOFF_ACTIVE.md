# Active Claude/Codex handoff

Last compacted: 2026-08-10 15:09 EDT. This is the executable mailbox.
Terminal markers live in `HANDOFF_REVIEW.md`, policy synthesis in
`AI_POLICIES.md`, job artifacts in `JOBS.md`, and queue order in `BACKLOG.md`.

## Immediate gate

**Externally review fresh capacity-v3 before Mini samples another world.**
The reviewed v1 label run consumed eight shard slots and then terminally
stopped: 2/8 shards completed, six refused, 971/1,024 rows completed and 53
refused. The other eight slots must never run, no aggregate exists and no
partial utility was mined. Safe telemetry proved the sampler itself succeeded;
v1 discarded repeated realized worlds until small-support late states could
not fill. That also biased posterior mass, so v1 is terminal no-use.

Capacity-v2 is also terminal no-use. Codex mistakenly treated its own marker as
independent review; bare Mini Python then refused all 32 samples while loading
V11 because NumPy was absent. It attempted zero candidate worlds and sampler
draws and retained no outcomes, but its one-shot slot is consumed and must not
be retried. Fresh source `167feab` / packet `b53eb509…ce19` keeps the exact iid
schedule while requiring Mini Python 3.14.6 + NumPy 2.5.1 to load and
fingerprint V11 before any admission can be spent. The exact external v3 review
request is at the bottom of `HANDOFF_REVIEW.md`.

In parallel, S4 source `fb6ec1a` is staged cleanly on idle Air. It defines a
fixed 2,048-cluster treatment/champion replication plus a 256-cluster null
sentinel (8,704 records), about 82% cheaper than the old confirmation. Runtime
and prior-screen parents reopen exactly; no preflight or outcome exists. Its
separate source review may authorize one score-free Air preflight only.

## Current truth

| area | current evidence | next legal action |
|---|---|---|
| Production | Release 17 runs compiled, formally confirmed `mc-s0-report-lcb`. | Monitor only; no production change is part of T4. |
| S4 point banking | **TERMINAL SCREEN PASS:** treatment−champion `+0.086914 +/- 0.056166`, one-sided LCB `+0.030748`; treatment−null is identical and null−champion is exactly zero. Cheaper fixed Air source `fb6ec1a` is staged with exact parents; zero new worlds. | External source review; on PASS run one 8-cluster score-free Air preflight. Only a passing projection can open a separately reviewed replication packet. |
| H0 human/V11 diagnostic | **TERMINAL NO-USE:** 555/557 complete, two score-free refusals, status `REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY`. | No retry and no partial-row mining. Stage C admits no human-derived proposer. V11 remains only its separately frozen bounded proposal source. |
| Stage-C capture | **V7 TERMINAL CAPTURE PASS.** Claude passed `03c87d6` / `b53af06c…8a43`; one fresh receipt produced 24/24 shards. All 750,000 dispositions and 2,048 selected states replayed exactly. V3/v6 remain terminal no-use. | Preserve the consumed receipt, shards and verifier. Never rerun, pool or extend. |
| Stage-C state set | **EXTERNAL PASS.** Exact `1024/512/512`, play/bury `1920/128`; state set `c7a769c4…e8e1c`, verification `143fb2db…4adb`. Claude independently recomputed population/digests and authenticated all disposition replays. | Preserve. Never rerun, extend, pool or mutate. |
| Stage-C labels | **V1 TERMINAL NO-USE:** two complete/six refused shards and no aggregate. **Capacity-v2 TERMINAL NO-USE:** result `64fdda5f…4cf2`, 32 dependency refusals, zero candidate worlds/sampler attempts/outcomes; its self-review launch was invalid. **V3 REVIEW OPEN:** source `167feab`, packet `b53eb509…ce19`, exact V11/NumPy pre-admission witness and no v3 slot/result/world. | Claude external capacity-v3 packet PASS; then one outcome-discarding Mini run and result review. Only afterward may a fresh label-controller packet be frozen and separately reviewed. |
| Stage-C model / REPORT | Iid-v2 head `8a202e9` descends from integrated `42e1726`, retains the cross-Git repair and bumps downstream schemas so v1 cannot masquerade as v2. Focused tests pass 51/51 on Mini and the compiled Stage-C/S3c slice passes 184/184 on Air. No checkpoint or REPORT look exists. | Training remains closed until complete reviewed iid-v2 labels and a new training-packet review. REPORT stays sealed until DESIGN/CALIB selects one capability. |
| Stage-C composition | The reviewed composition behavior remains unchanged beneath iid-v2: literal live candidate zero, at most one model proposal, report-LCB override decider and same-work random null. No packet/run. | Rebind and execute only after one REPORT passer, then capacity and one same-work whole-game screen. |
| S6 throw sourcing | Draft PR #19 head `cfa5a53` now implements the new contract without touching production: whenever any effective-suit holding permits a multi-component lead, an append-only widened ballot contains at least one shuai in early/mid/late. The old source failed a natural late trump-only seed-1 state; v2 adds a bounded trump fallback. Literal live ballot/candidate zero remain first; 11 focused and 58 broader tests pass. | Defer its external source-semantics review while the capacity packet/result is the immediate gate. Review must preserve public/lead-only inputs, ≤8 additions, no-op/follow negatives and equal-work later evaluation. Source PASS still cannot authorize a screen. |

## Downstream implementation ready without execution authority

V1 source `3f6f048`, packet, receipt, eight consumed slots and shard artifacts
are immutable terminal evidence. Fresh v2 source `8a202e9` is a descendant of
integrated `42e1726`; it keeps the cross-commit authentication and composition
behavior while replacing only the invalid world-identity uniqueness rule and
bumping all affected schemas. An old parent Git remains acceptable downstream
only with its exact packet and byte-identical label sources. Air passes the
184-test compiled Stage-C/S3c slice at exact v2 head. Composition still
preserves literal live candidate zero, proposes at most one model-ranked
alternative, leaves report-LCB as the override decider and includes a
trigger/work-matched random null.

None of those source results authorize labels or training. Capacity-v3 packet
review is the current gate; composition can execute only if the one-shot
REPORT evaluation eventually selects a capability.

## Compute sequence after state-set PASS

1. Obtain exact Claude review of capacity-v3 packet `b53eb509…ce19`.
2. On PASS, Mini runs that one outcome-discarding 32-state capacity probe from
   its exact Python 3.14.6 / NumPy 2.5.1 environment.
   Externally review its terminal result before freezing anything downstream.
3. Freeze and externally review a fresh iid-v2 label-controller packet. Only
   then execute all 16 shards with eight workers and aggregate on 2,048/2,048
   complete rows with zero refusals.
4. Review the aggregate and freeze/review the v2 training packet. Mini then
   runs 48 cells (play/bury × eight seeds × 25/50/100%), at most eight
   concurrently. Air remains isolated to the separately gated S4 lane.
5. Select one capability only from DESIGN/CALIB, open sealed REPORT exactly
   once, compose the passer inside report-LCB with incumbent fallback and a
   same-work null, then run a fresh whole-game screen against the live champion.

## Safety boundary

- V3 is terminally held. Do not reuse its receipt or six partial shards, retry
  its deterministic failures, delete/reissue its receipt, or start later waves.
- V4 passed its phase review and v5 was held; both were superseded before
  admission. V6 is terminal no-use after one admitted execution: preserve its
  receipt and 24 shards, and never retry, extend, pool or derive a state set.
- Capture-v7 is consumed and terminally verified. Never issue another receipt,
  retry a shard, extend the population or mutate the frozen state set.
- Label v1 is terminal no-use. Preserve its global receipt, eight shard locks
  and eight shard artifacts; never run untouched slots, aggregate, pool or
  inspect partial utilities.
- Capacity-v2 is terminal no-use. Preserve result `64fdda5f…4cf2` and consumed
  slot `b6c1219a…5e72`; never retry it or treat Codex's own marker as external.
- Do not retry H0, inspect its 555 partial utilities, or derive a human rule.
- Do not launch S4 confirmation, S3a, S6 or an unreviewed Stage-C stage merely
  to occupy an idle machine.
- Do not open REPORT during capture, capacity, labels, training review or
  DESIGN/CALIB selection.
- The T4 goal stops before confirmation, promotion or deployment.
