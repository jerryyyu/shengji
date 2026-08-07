# Fleet job ledger — mini (this machine)

The Air keeps its own at `~/Projects/shengji-compute/JOBS.md`, which is also
the inter-agent mailbox. Keep one authoritative running section here.

## RUNNING / exact-runtime S0c-adaptive-LCB (Mini)

Mini is the authoritative S0 pipeline. At 22:55 EDT all eight S0a shards began
from fresh exclusive outputs in detached clean worktree
`/Users/jerryyu/Projects/shengji-s0-mini`, frozen at full HEAD
`be1e39cd9281f752d610ff770f6a280098024388`. They run as durable
`com.shengji.s0mini.s0a.0`…`.7` launch services under Python 3.14.6 with strict
voids and compiled binary SHA-256
`9c9e77fbdc4c6caceec195465155f37ec6369e409462fd838bc142bf8a0be4c1`.
S0a completed 8/8 clean shards at 06:58 EDT. The registered frozen-source
aggregate selected `mc-s0-report-lcb`: `+0.353 +/- 0.069` versus current,
`+0.293 +/- 0.066` directly versus equal-work uniform, with the true null flat
at `+0.008 +/- 0.070`. Aggregate SHA-256 is
`0fcd53d4f782a705bfef9ea8ec6155c49db45d76ec71ce25891a9f864413de49`;
independent recomputation matched except for the stored file's absent terminal
newline. This is not promotion. At 06:58 the singleton supervisor launched
8/8 `s0b-lcb` shards over exact seeds 134,000,000–134,002,047. Every child
binds that aggregate and survivor and preflighted frozen SHA/runtime/native
identity with strict voids, no dirty files and zero stderr.
S0b-LCB then completed all eight clean shards. The exact registered aggregate
selected `mc-s0-adaptive`: adaptive-minus-report-uniform
`+0.037109 +/- 0.060294`, adaptive-minus-random `+0.433105 +/- 0.064534`,
adaptive-minus-current `+0.394531 +/- 0.067480`, and null-current
`+0.008301 +/- 0.067274`. Uniform report-LCB itself was
`+0.357422 +/- 0.065866` versus current, nearly exactly replicating S0a.
Aggregate SHA-256 is
`25c0177e27c0e185e96701ad788313a7ea14b892e24586186df02466bf144803`.
The point-estimate allocation gate selected adaptive; this block cannot
promote. Its incremental interval crosses zero, and report-uniform also beats
random by about 0.396, so the substantive result is report-LCB replication with
no measurable adaptive-allocation gain.

At the transition, the supervisor refused before aggregation because its exact
audit-tool hashes were from `6fe5f44` while `S0_AUDIT_ROOT` still defaulted to
moving main. No aggregate existed and no evidence changed. Codex created clean
detached `/Users/jerryyu/Projects/shengji-s0-audit` at full
`6fe5f444983bd43d10e081c92acd62c8f7403b74`, verified all three expected
hashes and resubmitted the same singleton with only that root repointed. At
17:30 it sealed S0b and launched all eight `s0c-adaptive-lcb` shards over exact
seeds 135,000,000–135,008,191. Launchd/static-wrapper inspection confirmed all
four experimental keys absent and only compiled+strict flags added. At 17:31
the supervisor and keepawake service were live, all eight S0c workers ran near
95% CPU, eight partial pairs existed and there were zero final/FAILED artifacts.
Independent review then found all eight sealed S0b keepalive labels repeatedly
restarting only to hit exclusive-output refusal. Codex removed exactly those
eight completed labels after verifying finals and aggregate; the loaded service
set is now exactly eight S0c workers plus singleton and keepawake. At 19:54 all
eight S0c launch services were still `running`, `runs=1`, with a live PID and
`last exit code=(never exited)`. Eight record/manifest partial pairs and zero
final/aggregate artifact existed; no outcome-bearing file was opened.

The original S0c iid analysis is **provisional**. The historical null's
+999,983 arm/team stream shift collides with evaluator opponent streams 17
clusters earlier, giving 8,175 dependency edges and 16,350 collided stream
keys. Frozen workers remain untouched. A separately frozen one-shot audit will
observe only terminal filename presence, seal exactly 18 inputs before parsing,
then reopen raw coverage/dose/counters/stats and analyze two globally
collision-free lag-17 parity populations of 4,097 and 4,095 seeds. Both must
independently pass all three original promotion criteria or corrected S0 is
SELECT NONE. No retry, extension, pooling or fallback is allowed. The obsolete
147M S0e-v1 path is irreversibly retired; its collision-free v2 replacement is
only a preterminal 148M parent authority seam, not a runner or job.

At 17:02 a last-line progress check established that worker stdout
contains interim W/L and therefore is not score-blind. The observed values are
quarantined and caused no code, dose, launch, stop or estimand change; do not
open these stdout logs, supervisor state or JSONL partials again. Future
heartbeats are process/artifact-count only. The frozen worker commit/runtime
are unchanged. Commit `7314cdf` suppresses both interim W/L and shard-end paired
effects for future main runs; it does not alter this frozen live block.

Air's S0a duplicate is no longer needed now that authoritative Mini passed its
aggregate gate. Its exact S0 workers are no longer running and its transition
supervisor remains stopped, so it cannot independently launch S0b. Historical
duplicate records remain inadmissible; never pool or double-count Mini and Air.
The initial Python-3.14.3 Mini
shard 7 was stopped after preflight exposed the mismatch and remains quarantined
and unscored under `runs/logs/quarantine_s0a_python_mismatch/`.

## COMPLETE / V11 direct-current compatibility v1 (Air; FAIL as run)

At 11:56 EDT eight full shards launched in detached screens `v11_current_0`…`.7`
from clean detached worktree `/Users/jerryyu/Projects/shengji-v11-air` at exact
commit `e66b90bc3a50d514472670ea99909add5ea30d19`. The block is 8x256 fresh deal
clusters over contiguous seeds 121,000,000–121,002,047. All eight provenance
manifests agree on Python 3.14.6, compiled+strict execution, policy/ballot/digest
contracts and checkpoint SHA-256
`cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003`;
the worktree remained clean. All eight real shards completed with no partial,
FAILED, sampler rejection/failure, short-search or zero-world residue. The
frozen aggregate ran once with the `_SMOKE` artifact excluded. Results per
paired seed were:

- v11-current: `-0.132324 +/- 0.069737`;
- v11-null: `-0.159180 +/- 0.069282`;
- true null-current: `+0.026855 +/- 0.067875`.

Both efficacy LCB criteria failed, the null interval contained zero, and the
stored verdict is `anchor_test_authorized=false`. Aggregate:
`runs/logs/v11-current-v1.aggregate.json`, SHA-256
`112f2c756235d69ac60efbd0f263ef096d311145d0151931ce2a2b8b0099eaec`.
This is terminal evidence for exact commit `e66b90b`; never overwrite or
reinterpret it. Its recorded encoder digest contains the silent banker-private-
kitty drift fixed by `66aad44`, so it does not isolate the intended historical
v11 model/encoder contract. A corrected, versioned direct block must use fresh
disjoint seeds before corrected protected composition can launch.

## REFUSED / teacher-v1 supervised entry packet v1 (Air; closed before diagnostics)

After the V11 aggregate sealed, Air's clean detached teacher worktree was
repointed to minimal commit
`0183cdd105ca6074d3824fe294f39a2986b15bb8`, which includes the explicit
public/no-private-kitty encoder fix and fail-closed entry supervisor. Exact
compiled+strict preflight passed under Python 3.14.6 with checkpoint SHA
`cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003`
and no output collision. At 14:55 the supervisor admitted packet
`teacher-v1-entry-120m-v1` and launched all eight capture workers over exact
seeds 120,000,000–120,001,023 (8x128).

All eight captures completed with zero child failure. Before launching any
diagnostic, the supervisor re-opened them and refused all eight as "actor
drift." Metadata-only diagnosis proved the executable actor did not drift:
source hashes, ballot values and semantic identity are identical; the worker's
JSON artifact represents `BallotSpec.config` as lists while the supervisor's
in-memory object retained tuples, and direct dict equality rejected the
round-trip. The fail-closed boundary therefore prevented downstream work.

The directory `runs/logs/teacher-v1-entry-120m-v1` is a terminal refused
attempt: eight capture finals, zero diagnostics, zero state set, zero receipts,
zero labels, and a `REFUSED` supervisor progress tail. Do not resume, replace or
reuse it. A replacement must use a fresh versioned 143M namespace and disjoint
seeds, canonicalize actor identity through JSON, enforce Python 3.14.6 and
reject every experimental sampler/ballot flag before launch.

## READY / teacher-v1 supervised entry packet v2 (no job launched)

Commit `2038b31` is the independently accepted fresh 143M-v2 entry gate. It
closes JSON-canonical actor identity, exact Python/flags admission, exact
8-shard/1,024-deal capture admission, full capture -> diagnostic -> selected-
state byte binding, recomputed coverage, 64 unique in-range states, Stage-A/B
disjointness and exclusive publication. Its scope stops at the 64-state freeze.
Air is occupied by corrected V11 v2, so no teacher-v2 process or namespace has
been started. The actual supervisor and every later consumer must execute at
exact full commit `acfd95b3088d73b53abda987a12e6be552da0b2b`: its accepted
entry/state/contract bytes are unchanged from `2038b31`, and it also closes the
receipt/label/gate writers with exclusive post-link verification, exact parent/
runtime/source reopening and recomputed Stage-A/B decisions. Capturing at
`2038b31` and switching later would be rejected as Git/runtime drift. Run the
fresh singleton on one Python-3.14.6 compiled+strict host through exact 64-state
freeze, then stop before receipts or labels; never migrate phases between hosts.

After V11 releases Air, move only the clean detached Air worktree to full
`acfd95b3088d73b53abda987a12e6be552da0b2b`; require the exact output namespace
to be absent and no older supervisor live. From its `server/` directory, run:

```bash
env -u SHENGJI_WEIGHTED_SPLITS -u SHENGJI_UNIFORM_DEAL \
  -u SHENGJI_PHYSICAL_FILLS -u SHENGJI_ALLOW_BALLOT_MISMATCH \
  SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 PYTHONDONTWRITEBYTECODE=1 \
  /opt/homebrew/bin/python3.14 -c \
  'import sys; sys.path.insert(0,"scripts"); import teacher_v1_entry_supervisor as s; s.preflight("teacher-v1-entry-143m-v2","acfd95b3088d73b53abda987a12e6be552da0b2b"); print("TEACHER_PREFLIGHT_PASS")'
```

Only after that exact PASS, start one durable Air singleton with the complete
cleaned environment (never bare `nohup`):

```bash
screen -dmS teacher_v1_entry_143m_v2 \
  /usr/bin/env -u SHENGJI_WEIGHTED_SPLITS -u SHENGJI_UNIFORM_DEAL \
  -u SHENGJI_PHYSICAL_FILLS -u SHENGJI_ALLOW_BALLOT_MISMATCH \
  SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 PYTHONDONTWRITEBYTECODE=1 \
  /opt/homebrew/bin/python3.14 scripts/teacher_v1_entry_supervisor.py \
  --packet-id teacher-v1-entry-143m-v2 \
  --expected-git acfd95b3088d73b53abda987a12e6be552da0b2b \
  --out-dir runs/logs/teacher-v1-entry-143m-v2
```

Air owns this successor after V11; Mini remains reserved for Direct-Q after
terminal S0. The supervisor emits a 30-second heartbeat and owns 8x128 interleaved 143M
capture -> eight diagnostics -> exact 64-state freeze. Its required terminal
is `STAGE_A_STATES_FROZEN`; review that parent before any receipt/label work.

## RUNNING / V11 corrected-encoder direct v2 (Air)

Commit `cde0fec` freezes eight 256-cluster shards over exact fresh seeds
142,000,000–142,002,047. The claim is only whether the unchanged `ep07.npz`
direct override is compatible with restored public/no-private-kitty encoder v1
against current compiled `mc-strong`. It binds combined encoder identity plus
encode/Memory source hashes, exact checkpoint and policy/ballot/runtime bytes,
requires every N=30 cell to consume exactly `30 * searches` accepted worlds
with zero failures/refusals/short/zero-world/exact-feature use, keeps shard
progress score-blind and reopens raw records at aggregation. Historical v1 is
explicitly inadmissible. A PASS is not production or protected-composition
authorization. Root focused tests passed 49/49 and compiled+strict protocol
preflight returned no problems. Air was pinned to exact clean full commit
`cde0fecf4151685e7174be8a7aa64b0ee6478edd`; at 15:25 eight detached shards
launched. At the 17:32 metadata-only check all eight Python workers remained
live at roughly 83–87% CPU, with eight record partials, eight manifest
partials, zero final/FAILED artifact and no namespace collision. Do not inspect
partial scores. Aggregate
exactly once only after 8/8 real finals, 8 matching final JSONLs, zero
partial/FAILED artifact and zero worker/screen residue. The operator terminal
guard is required because the frozen loader does not reject unrelated residue
names. Use only clean detached
`cde0fecf4151685e7174be8a7aa64b0ee6478edd`, runner SHA-256
`9bc265ad3be7e7de40bd70b8c8446c4d2d163918d342ffd56f50173d22d23da2`,
`/opt/homebrew/bin/python3.14` == 3.14.6 and all four experimental keys absent:

```bash
env -u SHENGJI_WEIGHTED_SPLITS -u SHENGJI_UNIFORM_DEAL \
  -u SHENGJI_PHYSICAL_FILLS -u SHENGJI_ALLOW_BALLOT_MISMATCH \
  SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 PYTHONDONTWRITEBYTECODE=1 \
  /opt/homebrew/bin/python3.14 scripts/v11_revalidate_v2.py aggregate \
  --pattern 'runs/logs/v11-current-revalidation-v2_shard0[0-7]_cde0fecf41.jsonl.manifest.json' \
  --out runs/logs/v11-current-v2.aggregate.json >/dev/null
/usr/bin/shasum -a 256 runs/logs/v11-current-v2.aggregate.json
```

Run from `/Users/jerryyu/Projects/shengji-v11-air/server`, never moving main.
Bind the resulting hash into protected composition regardless of PASS/FAIL;
preserve the direct verdict and `protected_composition_authorized=false`.
The loader separately requires a sane null and exact dose. This artifact has
no activation counter and cannot prove that the network influenced a play.

## READY / dependent strength code (no job launched)

Corrected-parent protected composition is frozen at `b361836`, with empty-
valued sampler/ballot environment-key refusal closed at `1354cac` and future
policy-owned activation accounting at `c8358d2`. Commit `e026ed0` adds the
future four-source cards/combos/encode/Memory identity through composition
shard, aggregation and confirmation while leaving the frozen live parent bytes
and two-source receipt exact. It remains launch-locked by
`DIRECT_AGGREGATE_SHA256=None` until this live V11 block seals and also waits
for terminal S0. Direct-Q's bounded learning screen is accepted at `7dbee75`:
three exact treatment/no-step seeds, score-redacted preflights, separate
iteration-256 resume, held-out seeded semantic replay, paired utility and
terminal mutable-state reopening passed independent review and 95/95 focused
tests. No Direct-Q process exists. Run its six 32-iteration preflights on Mini
only after S0 releases capacity; review wall/storage before any full segment.
None of these commits changes production.

## FROZEN PROTOCOL — S0a decision-rule screen

- Policies: `mc-s0-report-mean`, `mc-s0-report-lcb`,
  `mc-s0-uniform-work`, `mc-strong-null`, `mc-strong`, all paired on the same
  deals against current `mc-strong`.
- Dose: uniform N=30 selection; report R=300; report/equal-work arms consume
  exact `30K+600` candidate rollouts per contested decision. Eight shards of
  256 clusters; aggregate only with the hash-pinned `6fe5f44` verifier and set
  `S0_SOURCE_SERVER` to the frozen Mini server. The singleton supervisor owns
  this invocation; do not launch a competing manual aggregate.
- Calibration asset: `server/tests/data/s0_override_audit.v1.json`, SHA-256
  `9703b50817fb03622c3739e44f73e19083b1e8337300be7054774e2308e13ef5`.
  Clean producer `df0a7b9`; 150 states, 48 incumbent overrides, first 20
  detailed, 12 positive N=300 gaps, mean +0.570, R=300 selected by the committed
  rule.
- One dirty two-cluster local smoke at the frozen R=300 dose completed all five
  arms (20 mirrored records) with zero short/zero-world or unreconciled
  searches and no manifest problems. It is marked `promotable:false` and is
  mechanics only; its game scores are not evidence.
- Frozen coverage: authoritative Mini `I=0..7`; Air `I=0..7` is fallback only.
  A launch counts only after the live process, log and `.partial` manifest are
  all observed. Both hosts use Python 3.14.6 and the exact native hash above.
- The entire conditional chain is predeclared before S0a is inspected. S0b
  requires the exact S0a aggregate via `--parent`; S0c requires the exact S0b
  aggregate. S0c uses seeds 135,000,000–135,008,191, 8x1,024 clusters, one
  frozen survivor plus `mc-strong-null` and current. Its final gate requires
  survivor-current and survivor-null paired 95% lower bounds >0 and a null that
  does not clear. No extension is authorized.

**SAMPLER CERTIFICATE — CURRENT.** `server/runs/logs/certify_sampler_v3.json`,
git `aea3774`, clean tree, compiled ACTIVE, strict voids ON. 1,500 states at
500/500/500 across original/late/deep; 36,000 requested = accepted; 0 rejected,
0 invalid, all four skip counters 0; 120/120 toys reachable with the real deal
reached in all. `certified: true` with `scope_failures: []`. Artifact SHA-256:
`e31e67f9aeb4739aa598faa66051ec4004fd47751b297457242dc95a30cc224c`.

SUPERSEDED, and none of them was original+late+deep certification: `eea78d2`
(original-only — one global counter across ordered paths starved `late`),
`c1ceca1` (same defect plus 40/40 toys against a registered 120), and the dirty
v2 run (generated pre-commit, `tree_dirty=true`).

Codex reviewed and **ACCEPTED / CLOSED** package H on 2026-08-05. Posterior
fidelity and global constructive-dealer completeness remain separately open;
neither blocks the strength queue.

## FINISHED — decision-sensitivity screen (Codex's unblocking condition), 06:05

Does the sampler's posterior bias change WHICH ACTION is chosen? Fixed value
table per (action, world) so rollout noise cannot vary; compare argmax under the
exact physical posterior, N=30 from the real sampler, and N=30 from the exact
posterior as a CONTROL that absorbs Monte Carlo noise.

- 30 decision-LIVE states, 600 reps: excess disagreement `-0.0066 +/- 0.0169`,
  excess regret `-0.0098 +/- 0.0171`. Both include zero; sign flipped between
  the 12- and 30-state blocks, so read neither point estimate.
- **54 of 84 enumerable states are DECISION-DEGENERATE** — every candidate
  identical on every world. The harness excludes and counts them and REFUSES if
  none remain, because there a broken probe and a perfect sampler both print
  0.000.
- NOT harmless per state: only 9/30 live states disagree at all, with excess
  from `+0.158` (bias nearly doubles the error rate) to `-0.160` (bias helps).
- Fill-failure retry reweighting RULED OUT here: 0 failed draws in 540,000 attempts with 0 failed draws (recorded in the v2 artifact)
  empty `reject_cause`.
- Screen, not preregistered; population is small, endgame-heavy and
  unrepresentative of the deep-lead states the pilot scores. Gate NOT called.

## FINISHED — reference repair + residual attribution, 2026-08-05 03:10

Physical-deal reference implemented and brute-force verified (`AABB 2/2` -> 6,
`AABBCC 2/2/2` -> 90). All blocks reweighted from stored histograms, no
resampling. Weighted splits CONFIRMED at `-0.0600 +/- 0.0310` against the
corrected reference (larger than the `-0.0514` flat figure, so not a reference
artifact). `PHYSICAL_FILLS` adds `-0.0031 +/- 0.0048` — below resolution, 22/24
states unchanged, 0 worse. Residual attributed: split-choice TV `0.0697` vs
card-choice `0.0330`, so it remains in `_splits` after weighting. Off-support
sampled mass is 0.0000 everywhere. Nothing adopted, all flags OFF.

## FINISHED — 103M `mc` vs `mc-prefix` bot-layer contrast (Jerry's ask)

**Strength: NOT CONFIRMED, and PROVISIONAL — do not quote as a clean result.**
`arm minus reference -0.054 +/- 0.156`, n=504, includes 0. Win rates 48.3% arm
/ 49.0% reference / 52.1% control. The aggregator REFUSED a pooled number
(4 zero-world decisions, all in `control`); the figure above is its
`--allow-problems` provisional read.

**This contrast cannot be made clean by rerunning, and that is the finding.**
The protocol failures are produced BY the thing under test. Per-side counters:

```
  label/side          searches   rejected   zero
  arm/arm   (current)    30757          2      0     0.00007  <- only current row
  arm/opp   (pre-fix)    30685        410      0
  control/arm(pre-fix)   30667        507      2
  control/opp(pre-fix)   30619        519      2
  reference/arm(pre-fix) 30609        493      0
  reference/opp(pre-fix) 30618        578      0
  ------------------------------------------------
  ALL sides                          2,509      4
  pre-fix aggregate    153,198      2,507            0.01636
  current                30,757          2            0.00007   ~252x lower
```
(Corrected 2026-08-05: an earlier version of this table omitted the `opp` side
of `control` and `reference`, so it displayed partial counts. Codex caught it;
the totals above are re-derived from the raw shards.)

The pre-fix bot layer rejects 2,507 of 153,198 sampled worlds (1.64%); the
current bot rejects 2 of 30,757 (0.007%), a ~252x lower rate, and produces no
zero-world fallbacks where the pre-fix layer produced 4. This is a DESCRIPTIVE
post-hoc screen, not preregistered and protocol-failed. So the
strict evaluator's own no-zero-world requirement is violated by `mc-prefix` BY
CONSTRUCTION. Any rerun hits the same wall; only a changed estimand escapes it.

**What this does and does not say.** It quantifies, for the first time, what the
correctness work bought: a ~250x reduction in constraint-violating world
proposals and the elimination of zero-world fallbacks, measured with both bot
layers on the SAME current engine so engine changes cancel. It does NOT show a
strength gain — the level-utility contrast includes 0. Correctness and strength
are separate axes here and only the first moved. `mc-prefix`'s ballot digest
also differs (`4d73f8cb` vs `a68f7b8b`), so this is a whole-bot-layer contrast,
not a sampler-only one.

## FINISHED — Gate 3 raw capture (not scoring)

Fresh schema-v2 capture and merge completed at 23:15 from clean compiled+strict
`836cc07`. Independent validation replayed all 768 unique rows and confirmed:

- 256 DEV / 256 CALIB / 256 REPORT;
- exactly 16 rows in every split/trick-12..19/role cell and 128/128 role
  balance per split;
- zero accepted-path sampler counters, illegal actions, engine errors or
  scored values;
- 12 rejected proposals across 9 excluded deals, with zero observed
  zero-world/impossible-world events;
- data SHA-256
  `ffccfde64932eb3a0129765f3ba903099f2e5c1da16a8287aebd0024f3456982`.

The first v1 attempt remains recoverably quarantined. Gate 3 capture is closed;
do not rerun it.

## PILOT — DEV-512 COMPLETE, SELECT NONE; CALIB/REPORT SEALED

Gate sets: `pilot_dev512.v6.json` `af78748586034f6f`, `pilot_calib512.v6.json`
`3872350f57a4dd60` (byte-unchanged, never scored).

**DEV 512/512 scored.** Eight clean shards at `884030f`, one experiment id
`a838d7415b4c2032`, bundle sha `38f61d4a9dacac6a`, aggregated exactly once with
no refusal. Codex independently reproduced both. Primary
`quota - random_fill` `+0.110 +/- 0.337` INCLUDES 0 -> **no ballot design
selected**. Aggregate retained at `runs/logs/dev512_aggregate.txt`; the seven
pre-fix shards are quarantined at `runs/logs/quarantine_prefix_75b06da/` and
were never combined.

**CALIB and REPORT remain unscored and untouched** — the contract runs CALIB on
one DEV-selected design, and there is none.

**Open:** global sampler completeness. `75b06da` is sound but necessary-only.

## FINISHED — N=30 frozen-current confirmation (seeds 102M)

**+0.222 +/- 0.140** vs N=10 over 504 preregistered fresh clusters;
arm-minus-null +0.230 +/- 0.139; null -0.008 +/- 0.154; win rates
55.2/50.9/51.2. So the `e3aeec1` result (+0.262 +/- 0.154) transfers to the
deployed executable despite sampler, ballot and decompose changes in between.
Caveat: these shards predate the `rejected_worlds` counter, so this is a
policy-as-run comparison, not proof of an exact accepted dose. Prod is live on
this (`mc-strong`, N=30, compiled engine); no redeploy without Jerry's go.

## RECENTLY FINISHED

### sampler posterior 24-state paired probe — SUPERSEDED, see the physical-
### reference block above (2026-08-05 03:10)

Kept only as a pointer. Two figures once published here are WITHDRAWN, not
merely superseded:

- the uniform-deal `+0.018 +/- 0.045` was computed over arms that shared 0 of
  24 enumerated legal sets — a sampler flag was live during state generation,
  so the "paired" statistic compared different states (Codex);
- the inference that the residual was an artifact of the flat reference is
  refuted: against the repaired physical reference the residual is 0.109 vs
  0.116, so the reference explained ~6% of it.

Current figures: weighted splits `-0.0600 +/- 0.0310`, uniform deal
`-0.0001 +/- 0.0027`, both 24/24 pairing-verified against the physical
reference. Nothing adopted; all flags OFF. (Superseded: DEV-512 has since scored 512/512 with SELECT NONE.)

### N=60 vs N=30 dose test — NO CONFIRMED ADVANTAGE, closed 2026-08-04 23:46
- Primary N=60-minus-N=30 paired utility **-0.002 +/- 0.119** over 504 fresh
  clusters; N=60-minus-null +0.004 +/- 0.129; null-minus-N=30
  **-0.006 +/- 0.134**. Every interval includes zero.
- One preregistered superiority block, no extension. This does not prove
  equivalence or saturation. The evaluator omitted rejected-world accounting,
  so interpret it as the two policies as run, not guaranteed exact accepted
  N=60/N=30 dose. Do not repeat without a materially different hypothesis and
  repaired counters.

### N=30 confirmation — CONFIRMED, closed 2026-08-04 23:40
- **+0.262 +/- 0.154** vs N=10 over 504 preregistered clusters (seeds 99M);
  arm-minus-null +0.310 +/- 0.153; null control -0.048 +/- 0.162 (includes 0).
  Independently reproduced by Codex from the raw six shards.
- **PINNED TO `e3aeec1`, NOT current main.** The action semantics and tractor
  ballot have changed since, and the manifest's ballot digest no longer matches
  source. Common-mode exposure preserves that contrast's internal validity but
  does not rule out an N-by-ballot interaction. Do NOT rerun to reinterpret the
  old result; a promotion of today's executable needs a FRESH frozen-current
  confirmation (Codex).

### action-semantics gate — CLOSED by Codex 2026-08-05 at `a2560ba`


### rewritten-sampler N=30 confirmation — CONFIRMED 23:43
- Preregistered one-block result: N=30 minus N=10 `+0.262 +/- 0.154`; N=30
  minus the true `mc-null` control `+0.310 +/- 0.153`; null minus N=10
  `-0.048 +/- 0.162`, all over 504 fresh seed clusters.
- Six equal 84-cluster shards, seeds 99,000,000-99,000,503, no extension and
  no pooling with the 96M screen. Aggregation reported no protocol problems.
- This certifies the version-pinned pre-action-fix result. Current `main` has
  since changed decomposition and the tractor ballot digest; require a fresh
  frozen-current confirmation before promoting today's executable, rather
  than reinterpreting or pooling this historical block.

### sampler certification — HISTORICAL; population claim withdrawn
- run eea78d2, clean tree. 1,600 reservoir states / 38,399 worlds, 0 invalid.
  120/120 constructed toy states fully reachable, real deal reached in all.
- Found and fixed a second sampler defect on the way: tractor run-length caps
  were never consumed. Three certifier bugs of my own also fixed.
- Later audit proved the global limit consumed only `original` rows: zero late
  rows were tested and no replay-skip counters existed. Preserve this as defect-
  finding evidence, not a closed P0 certificate. Distribution fidelity was
  never certified.


### sampler certification — 20:10, found and fixed a real defect
- 64,795 worlds across early and late ply. 12 invalid at ply>=16, all from the
  declarer pin completing a pair the cap forbade. Fixed and re-certified clean.
- Distribution fidelity explicitly NOT certified; two biases named in
  AI_POLICIES.md.

### dose contrast rerun — 19:00
- Clean aggregation, but the formal verdict is void: I passed `mc-strong` as
  `--control`, and the evaluator's control means "an arm that should NOT work".
- Measurements: N=10-N=5 +0.369 +/- 0.221; **N=30-N=10 +0.290 +/- 0.210**,
  which REOPENS the determinization question on the corrected sampler. One
  block only — needs fresh seeds and a null control.


### ballot coverage audit (dev) — 17:40, CORRECTED
- 12,340 states, 0 rebuild errors. Structured omission 51.2% leads / 0.9%
  follows. Superseded the first run's 54.0%, whose structured filter wrongly
  accepted unrelated pair throws.

### late-ply capture (Air) — 15:30
- 540,000 attempts with 0 failed draws (recorded in the v2 artifact)

### determinization screen — CLOSED negative
- N=30 vs N=10 NOT CONFIRMED (+0.101 +/- 0.150, fresh seeds). N=10 vs N=5
  PROVISIONAL (14 zero-world fallbacks; the shards' own verdict was NOT
  CONFIRMED). Block 1 was contaminated by an aborted shard; corrected.


### determinization screen — CLOSED 2026-08-04, negative
- Three blocks, 756 seed clusters. N=30 vs N=10 NOT CONFIRMED
  (+0.101 +/- 0.150 on the two confirmation blocks). N=10 vs N=5 has a strong
  secondary contrast (-0.347 +/- 0.145), but 14 zero-world fallbacks make it
  provisional under the evaluator's own protocol. Do not deploy N=30; rerun
  the dose check only after the constraint-correct sampler lands.
- Full ledger in AI_POLICIES.md.


- **ckpt_v13abs absolute-Q leaf** — NOT CONFIRMED (-0.004 +/- 0.206 paired vs
  the MC reference; v7 control +0.024 +/- 0.215). The direct paired v13-minus-
  v7 contrast is -0.028 +/- 0.185 with identical 52.8% win rates. Mis-aimed:
  trained mostly on ply<=15 `Q^H(s,a)` states and MCBot candidates, then
  deployed post-4-trick over the pinned-v1 `enumerate_actions()` ballot.

- **high-N corpus — COMPLETE** (Air, 247 min): 20,000 states x 240 shared
  worlds = 37.1M candidate evaluations, 31 MB, mean 7.7 candidates/state,
  5,283 (26%) with a best-vs-baseline gap clearing 2 SE. Synced to the mini
  with its manifest. Raw states rebuild exactly, but labels used the old
  non-strict sampler/current capped ballot and same-world maximum. This is a
  state reservoir and provisional `Q^Heuristic(s,a)` dataset, not an unbiased
  oracle, bracket target, or generic state-value target.

- **seeded Elo pool** — completed 21/21. Random-prune control ranked ABOVE the
  net-prior arm; all gaps <=28 Elo, inside the unresolved band. In AI_POLICIES.
- **race_confirm** — refuted the racing claim. Its manifest and JSONL were
  deleted by my own maintenance cleanup mid-run; only the aggregate log
  survives, so it blocks promotion but is not replayable.
- **V3 lead-ballot evaluation** — NOT CONFIRMED (+0.065 +/- 0.144 paired, the
  random-fill control higher). First claim through scripts/evaluate.py.

## STOPPED / INVALID

- **MC determinization scaling (N=30 vs N=10, N=5 control)** — INVALID. One
  of six strict shards aborted after 40 records at deal seed 93,000,146,
  flip 0, ply 46: `no worlds sampled for seat 3 (banker 3)`. The other five
  shards were terminated rather than burn compute on an aggregate that could
  no longer satisfy its preregistered contract. The public information is
  feasible (the real hidden hands provide a witness); the greedy sampler can
  consume capacity needed by constrained suits. Add this seed as a regression
  and replace the allocator with a constraint-correct sampler before rerun.
- **mini late-ply high-N corpus** — STOPPED at 617 states because it omitted
  `SHENGJI_REQUIRE_VOIDS` and `SHENGJI_STRICT_SAMPLING`. Raw states may be
  relabelled later; quarantine its N=240 labels.
- **mini high-N corpus** — DIED at 840/20,000. `nohup ... &` inside the agent
  tool does not survive its launching shell; use run_in_background.

## NOTES (mailbox — Air agent, read this)

- Every strength claim now goes through `scripts/evaluate.py`, which enforces
  its `--bar`, requires a control and SHENGJI_REQUIRE_VOIDS, and fails closed
  on a dirty tree. Do not report strength from any other path.
- The dev server on :8899 predates the LOG_DIR change and writes local test
  games into the human corpus dir. Check `logs/` each pass.
