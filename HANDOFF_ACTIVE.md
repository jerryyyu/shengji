# Active Claude/Codex handoff

> Current operational truth and precise review queue only. Historical review
> rounds belong in `HANDOFF_REVIEW.md` and Git history. A request not listed
> here is not active.

Last reconciled: 2026-08-25 12:48 EDT.

## Immediate objective

Obtain a decision-grade answer on whether actor-visible public history improves
hidden-card ownership prediction. Finish and independently reproduce R4, then
run one efficient recoverable R5 chosen in light of R4's result. R4 and R5 use
the same scientific population and are not independent replications. Neither
authorizes gameplay, strength, promotion, deployment or merge.

In parallel, PT0's sealed natural endgame result now supports designing PT1: a
fresh three-arm privileged-teacher acquisition screen whose primary bar is an
improved exact/full-information teacher beating production MC given the same
true world. PT1 is isolated to Mini and cannot touch R4/R5.

## Review queue — two precise asks, one pass each

### 1. PT1 PR #145 `95a142d` + `r3` — NARROW SOURCE REPAIR + FREEZE

Review this once as the repaired-head successor to Claude's exact `r2` HOLD at
`4620fac`; do not repeat the already-PASSed PT1 search/statistics/design audit.
Exact head is `95a142de0f04e524c9ac0565ac8e541de26974af`, parent
`9ff7a2b3ca6704042d2394c5a57ff461171e4a93`. The four-file delta changes only
the Darwin boot primitive in both execution/capacity modules and adds one
failing-direction witness per module. Darwin now hashes
`kern.bootsessionuuid`; Linux still hashes `/proc/sys/kernel/random/boot_id`.
Both full PT batteries are 106/106 green. Mutating either command back to
`kern.boottime` turns its named witness red; both restore green. Live execution
and capacity probes independently returned the same real session UUID hash
`60b50967…11212` twice, while a simulated session-UUID change changes identity.

Fresh score-free capacity at `/private/tmp/pt1-capacity-95a142d-r3` completed
16/16 with ten workers and no truncation. Capacity SHA-256 is
`f16a063821a1200f48bae5bf898510e4118693ee48ee45b1394318294872902f`;
manifest SHA-256 is
`56e1ba7cfe6b461a2886f4b6e21b2a72a2055d4b0a45415e4aa25ba8d1f94bd6`.
Recompute the six caps and score redaction, then review freeze
`/Users/jerryyu/Projects/pt1-freeze-95a142d-r3.json` (SHA-256
`2352967a3a6963dc24cae05ea8ebe24bed26bac834a68ea6121d0b67a18a9860`)
and marker `/Users/jerryyu/Projects/pt1-review-marker-95a142d-r3.json`
(SHA-256
`a9f6057fd65c7078335dfd080fc3c321554a57973179141fbd8681a0990d6f04`).
The independent freeze rebuild is byte-identical, and the real live
source/runtime/capacity binder passed twice after freeze. Fresh evidence root
`/Users/jerryyu/Projects/shengji-pt1-evidence-95a142d-r3` is absent. If exact,
append the byte-identical marker once and PASS this consolidated narrow repair
+ freeze. Jerry's standing PT1 launch GO carries over; Codex will launch once
through the proven normal Terminal/keychain path after PASS. Every gameplay,
strength, promotion, deployment, training, retry and merge authority remains
false. The dead `r1`/`r2` freezes must never launch.

### 2. R4 completion PR #146 `721b5f` — CONSOLIDATED SOURCE + FREEZE

Review this once at exact head
`721b5f8944f17718a833cfab051ff13cec1dfbfd` against exact parent
`5d3b129bae04e0afc6cd5369b206ea87a967731e`. CI is green. The exact eight-file
diff is the completion spec, worker/controller recovery route and its tests;
the original R4 source namespace remains immutable with no `calibration/`,
`terminal.partial/` or `terminal/` artifact. The fresh completion namespace
`/opt/belief-r4-completion-v1-r1` is absent.

Review packet
`/opt/belief-r4-completion-721b5f8-freeze-inputs-r1/freeze-review-packet.json`
was independently generated twice, byte-identical, SHA-256
`da8eef353b70afcb21bef72654d459654f7a14cd86652e42ce5fa923895538bd`.
It binds the read-only four-cohort audit `fb8cd058…d367`, active native
`f7d4deab…f246`, capacity `a8366214…d47f`, deadline
`566b6a4f…67a3`, caps `434b43de…5326`, exact freeze
`0d651819…f4f1` and expected marker `d65d61d2…6e86`. The score-free freeze
builder completed 100% in 4m03s with no evidence initialization or test open.
Verify the source stage gate permits only the pinned fresh completion route,
the sealed cohorts bind the exact original manifests, the general transport
fallback and legacy-cache compatibility are narrowly guarded, and the fresh
test opening cannot precede stable calibration. If exact, append the
byte-identical expected marker once and PASS. Codex will then run the
completion once and independently reproduce its terminal. No retry, gameplay,
strength, promotion, deployment or merge authority follows.

## PT0 result — closed and interpreted

Claude's authenticated terminal review is canonical at main commit `b8419bf`.
Exact source `bd4833f`, 104/104 records and the clustered bootstrap reproduced.

- Exact teacher minus heuristic and smart: mean `5/208 = +0.02404`; both 95%
  clustered intervals exclude zero. Local headroom is proven.
- Exact teacher minus production `mc-s0-report-lcb`: mean `35/1664 = +0.02103`,
  interval `[-0.00179,+0.04906]`. This is inconclusive.
- The result supports drafting PT1 only. No PT1 run, public policy, gameplay or
  strength authority followed from PT0.

## R4 — stopped before calibration selection or test opening

| field | exact binding |
|---|---|
| source | `d2d466f161eb8e55daf26677bfed361ad4110d7c` |
| freeze | `573fcade25d985f58c0d179a581a40619b5745fc2152c52f4740e1355ae1fc16` |
| admission | `21d9cea8a1ef2905dd0a8a85308e54141e58362e0764f04f388412bedfff0961` |
| host / unit | `shengji-cloud`; `belief-v2-r4-d2d466f-r1.service` |
| evidence / ops | `/opt/belief-r4-evidence-d2d466f-r1`; `/opt/belief-r4-ops-d2d466f-r1` |

R4 stopped at 2026-08-25 00:59 EDT with service result `exit-code`, status 1,
82/85 tasks and task-weighted progress 96.47%. All four 30-epoch cohorts,
checkpoints and reusable non-test artifacts remain sealed and untouched.
There is no `calibration/`, `terminal.partial/` or `terminal/` artifact and the
test-scoring controller never opened the frozen test population.

The failure was pre-test synthetic calibration projection:
`BeliefProjectionError: integral projection flow is infeasible`. Independent
read-only replay localized it exactly to seed `4807564651809522458`, rank `2`,
decision index 68 / key `666ee457…e135`, `synthetic-primary` member 6 / model
`ab68d94f…eec7`, after 4,742 successful member projections. The existing
general exact-transport fallback repairs this real prediction with maximum
cell movement 2.38 ppb and then passes full ownership validation. This is an
operational/model-path defect, not a positive or negative belief result.

Draft PR #146 now carries the fresh one-shot R4 completion route at exact head
`721b5f8`. It binds every original R4 input/training manifest, writes only to a
fresh namespace, proves stable calibration before a durable test attempt and
grants no retry/gameplay/deployment authority. Pure and strict BELIEF suites
were green before the live-artifact diagnostic. That diagnostic correctly
found a second pre-calibration compatibility seam: current code initially
rejected R4's exact legacy V2 tensor-cache accounting schema. The repaired
head permits that legacy schema only when the caller supplies the exact pinned
R4 cache-manifest SHA; ordinary V4 reopening still refuses it and wrong hashes
refuse. Focused tests are green. The actual sealed-cache/cohort audit passed
after 9,518.812 seconds and reopened all four exact 30-epoch training
manifests: primary `dfd992fe…`, label permutation `49a2490e…`, human mixture
`59016957…`, and scale-50 `af4d0287…`. It read roughly 176 GB without writing
evidence bytes; no calibration or test bytes were opened. The prepared
post-audit operator was hardened after the R5 score-free wrapper exposed Python
forkserver's `<stdin>` limitation. A final source-spec cross-check then caught
that the first operator named a different fresh destination than PR #146's
pinned `/opt/belief-r4-completion-v1-r1`; unit `r1` was stopped before it
published any receipt or freeze. The corrected operator now asserts the source
spec's destination before capacity work. Exact Bash SHA-256 is
`d89e2a93…52d0`, exact guarded capacity-runner SHA-256 is
`18e04d0e…e82`, and all output stages were absent before relaunch. The first
capacity attempt passed and then correctly refused a duplicate ignored native
under `server/build`; the build directory was moved intact outside the source
tree and the active frozen native remained exact. Continuation unit
`belief-r4-completion-freeze-721b5f8-r1c.service`, invocation
`fb6be5f43eb1448cb5ecc023641ad411`, then completed 100% successfully in 4m03s
under 24 GiB memory, zero swap and `Restart=no`. Capacity is
`a8366214…d47f`, deadline `566b6a4f…67a3`, caps `434b43de…5326`, exact
freeze `0d651819…f4f1` and marker `d65d61d2…6e86`. The consolidated review
packet was independently generated twice, byte-identical at
`da8eef35…38bd`; the fresh completion namespace remains absent. PR #146 is
now ready for the single consolidated source+freeze review above.

## R5 `r12` — stopped safely before training or test

PR #144 exact head `5d3b129` routes the reproduced R4 one-PPB residual
dead-end through the already-existing exact hard-bound transport fallback. A
direct minimal rerouting witness and the actual R4 calibration replay both
validate the repair; the real row moves by at most 2.38 ppb and then passes the
full ownership validator. The superseded `9e44c0f` / `r11` freeze must never
launch.

The fresh `r12` capacity receipt covers 416 rounds across all 13 trump ranks
and all 16 lanes. It derives the 65 capture-core-hour cap from measured bytes
using the fixed 1.25x rule. The uncontended deadline receipt measures a 6.35h
p95 training epoch and a 19.1-minute reserve against the unchanged 48h wall;
graceful truncation seals the best common epoch if patience has not converged.
The 64 GiB artifact and 30 GiB host-memory caps are unchanged.

The reusable cache import was full-byte reopened twice under exact repaired
source and freeze. Both passes returned the same five child manifests, counts
and 27,822,677,063 logical bytes. Neither produced a scientific namespace,
opened test or mutated the source cache. The independently reproduced
supervisor DAG has 85 tasks and keeps the sole test opening serialized.

The exact `r12` freeze and repaired source received the single consolidated
PASS at main `19b63f8`. Codex independently re-authenticated the append-only
Claude commit and marker, fetched canonical main on Performance Cloud, and
reran the independent freeze verifier: `verified=true`, source `5d3b129`, 11
inputs, 48 support artifacts, five cache children / 27,822,677,063 logical
bytes, scientific namespace absent and test unopened.

R5 initialized at 2026-08-25 02:50 EDT under
`belief-v2-r5-5d3b129-r12.service`, invocation
`bd1b850aa3bf4770a0fc4d132ef5a311`, with admission SHA-256
`70b15175edd62798c3cbd2d6b323bce1b206ae122d8629755e11bc3f616cedc8`.
It later stopped at task 47/85 (55.29%), `build-training-cache`, with
`ExecMainStatus=1`, `NRestarts=0` and exact refusal:
`BeliefV2TensorCacheControllerError: V2 tensor cache import input index drift`.
The imported cache's semantic training identity matched, but the controller
incorrectly required equality of the provenance-bearing wrapper index bytes.

No R5 cohort training, calibration or test opening occurred. All 13,312
synthetic captures, human capture/reference material and the 311,250,588-byte
training input index remain sealed and reusable. No imported cache result was
published. The admission is spent and must never be retried or deleted.

Draft PR #147 exact head `2d4dfe8` now carries the four-file semantic-identity
bridge. CI is green; pure BELIEF is 470/470, and strict x86 compiled is 468
green with the same three host/environment failures reproduced at stacked
parent `5d3b129`. The real source/r12 wrapper indexes and broad derived hashes
differ while their closed cache-determining identity matches exactly; changing
a true training-population field changes it and unknown fields refuse. The
score-free Perf receipt SHA is `3d3f8928…`. PR #147 remains draft and now has
the consolidated source+freeze review request above. Exact source is deployed cleanly at
`/opt/belief-r5-index-bridge-2d4dfe8` with an isolated validation environment.
The first score-free operator wrapper `r13` refused after 1.5 seconds because a
forkserver worker cannot reload a `<stdin>` main module. It created no receipt,
scientific namespace or data opening. The source remained unchanged; the
wrapper then used a real guarded module and fresh receipt namespace. `r13a`
completed all 416 rank-diverse capacity rounds in 6m39s at full 16-worker use;
canonical capacity SHA-256 is `48aef73e…2df1`. The serialized deadline step
then refused before sampling because the compiled-test checkout retained a
second ignored native library under `server/build/`; the exact execution binder
correctly classified it as an untracked loadable shadow. No deadline receipt,
scientific namespace, training, calibration or test opening was created. The
build tree was moved intact to
`/opt/belief-r5-index-bridge-2d4dfe8-build-artifacts-r13a`; the Git source
remained exact and clean. Deadline-only unit `r13b` then completed successfully
in 3m48s with no restart: 416 capture samples, 32 reference samples and two
matching training probes. Deadline receipt SHA-256 is `a22221d5…f361`; it
opened no production seed, retained no rows/models/worlds and authorizes no
pipeline or strength action.

The first exact-freeze build exposed one final deployment-runtime seam before
review or science: the newly compiled native library was byte-different from
the exact native library bound to the reusable 27.8 GB cache, even though the
Git engine sources are unchanged. The cache importer correctly refused
`source runtime/cap identity drift`; the fresh evidence root remained absent.
The new native was moved intact into the existing build-artifact quarantine,
and the previously frozen native binary (`e449d885…e3c`) was restored to the
active checkout. Fresh exact-native `r13c` preflights then completed: capacity
`cb3704c9…6f7`, deadline `10ae8be0…74d` and caps `70737c0f…d26`. The
successor freeze is `5bfeef78…f078`; its independent repeat is byte-identical.
The imported cache reopened twice with the same five child manifests and
27,822,677,063 logical bytes, the independently generated supervisor plan has
85 tasks with one serialized test opening, and the guarded launch script binds
all reviewed bytes. The review packet was independently generated twice at
`771e52f8…3453`. No scientific namespace, model training, calibration or test
opening occurred. Claude's single consolidated review PASS is canonical at
`9b1833312f874ad91ed43a75fd7ec5e82b83b6d1`; the appended marker is
byte-identical to the expected marker at `8237ea76…1448`. Codex independently
recompared those bytes, then authenticated the review against live canonical
main without initialization; the deterministic prospective admission is
`29421347…cd0d` and the scientific root is still absent.
PR #147 is fully prepared but must not launch before R4 is interpreted. The
actual packet path is
`/opt/belief-r5-index-bridge-2d4dfe8-freeze-inputs-r13c/freeze-review-packet.json`;
the native is bound transitively through the exact freeze, correcting the two
non-blocking wording defects in the review request. The superseded `r13a`
freeze `602d20b3…fb21` grants no execution authority and must not be reviewed
or launched.

## PT1 preparation

New isolated worktree `/private/tmp/shengji-privileged-teacher-pt1` branches
from exact PT0 head `bd4833f`. The proposed PT1 search design has three arms:
public production MC, true-world production MC, and exact true-world teacher.
Primary `C-B` measures policy improvement after both receive perfect
information; `B-A` measures value of information. The teacher must beat
production MC with a positive held-out lower bound, not merely beat heuristic.

Draft PR #145 exact pushed head `95a142d` contains the three A/B/C search arms,
natural 416-state provider, exact state-bootstrap statistics and a bounded
parallel Mini capacity preflight. It fails closed on
underfilled production work before persistence. The population is 416 distinct
engine-round clusters across all 13 ranks, two banker representatives, two
roles, two remaining-hand horizons and four replicates. C's deterministic
exact solve is now shared across the four policy seeds per state, eliminating
75% of duplicated C work while A/B stay seed-specific; checkpoints expose only
complete four-seed state groups. The capacity route measures ten-worker
capture and evaluation, counts shared C work once, projects the full scientific
wall/CPU/RSS/node/byte caps and retains no actions, values, points, raw seeds
or hidden worlds. The final execution controller preserves complete four-seed
groups, resumes only within one frozen deadline, discards late waves, and
cannot publish a valid packet after deadline. One clean-head Mini capacity run
completed 16/16 with ten workers and derived all six scientific caps. The exact
416-state `r1` freeze and canonical non-circular review marker received a single
consolidated PASS at `10cf7ad`; Jerry's GO is at `d348312`. Normal Terminal
authentication is proven. Claude's `r2` audit then found the Darwin boot
identity was incorrectly derived from the clock-adjustable `kern.boottime`,
not a reboot event. Exact four-file head `95a142d` replaces it with stable
`kern.bootsessionuuid` in both paths and carries two mutation-killing
witnesses. Fresh `r3` capacity/freeze is complete, passes the live binder, and
awaits only the narrow repaired-head review above. PT0 records are not reused
as training/evaluation data.

## Fleet

| host | current use | invariant |
|---|---|---|
| Mini | PT1 stable-boot repair + `r3` capacity/freeze complete; idle pending one narrow repaired-head review | Never rerun PT0; do not touch R4/R5; launch only after exact `r3` PASS. |
| Strength Cloud | R4 audit and fresh completion freeze PASS locally; idle pending consolidated PR #146 review | Never restart or alter the original R4 namespace. |
| Performance Cloud | R5 `r12` preserved; PR #147 exact-native consolidated PASS authenticated; idle pending R4 interpretation | Never retry/delete `r12`; do not launch R5 ahead of R4's decision. |
| Production | untouched | No deploy or policy change from research evidence. |

## Next operator sequence

1. Claude reviews the PT1 `r3` narrow repair/freeze and PR #146 completion packet;
   after their independent PASS markers, Codex launches both isolated runs.
2. Codex independently reproduces and interprets R4's terminal before any R5
   execution decision.
3. R5 PR #147 is already consolidated-PASSed and launch-ready but remains held.
4. If R4's result still justifies confirmation, Codex launches R5 once on the
   exact reviewed bytes. R5 remains confirmatory because it shares R4's
   scientific population.
5. Independently reproduce every terminal before any belief-to-gameplay or
   privileged-teacher-to-public-policy decision.
