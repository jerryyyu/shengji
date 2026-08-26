# Active Claude/Codex handoff

Last reconciled: 2026-08-25 23:59 EDT.

This file contains only current operational truth and precise review work.
Historical reviews belong in `HANDOFF_REVIEW.md`. Do not repeat a review that
is not named below.

## One active review ask — PT1 successor source + immutable r7 freeze

Review this once as a consolidated source/freeze packet. There is no separate
source-review, capacity-review or rehearsal-review round.

- Draft PR: #149, `codex/privileged-teacher-pt1-cap-repair`.
- Exact source head: `76508ec9c15638e715dc8d48ee6719412233918b`.
- Exact reviewed parent: PR #145 head
  `e27240e46981cae9db099236113a2b655d88570c`.
- PR CI: server and frontend green; merge state clean.
- Source validation: 60/60 PT1 tests pure and 60/60 strict compiled; `git
  diff --check` clean; source worktree clean.

The eight-file successor delta does three related things only:

1. replaces the old coupled 16-state capacity sample with an independent
   score-redacted 416/416 full-grid packet;
2. records exact sanitized cap overages and score-free worker failures at the
   production controller/CLI wiring; and
3. requires every captured scientific state both to expose at least two exact
   legal actions and to enter production's actual multi-candidate MC search.
   Tractor-locked leads and one-candidate production ballots are structurally
   ineligible. This predicate uses actor-visible state and deterministic
   production candidate generation only; it runs no rollout and reads no arm
   action, value, regret, point result or hidden-world outcome.

Exact immutable inputs on Mini:

| artifact | path | SHA-256 |
|---|---|---|
| capacity report | `/Users/jerryyu/Projects/pt1-capacity-76508ec-v1/capacity.json` | `7a4e84171cab5242398776adae1cc12c9f6bcce70f1e4cb9645db29c302c96dd` |
| capacity manifest | `/Users/jerryyu/Projects/pt1-capacity-76508ec-v1/manifest.json` | `b1b4c5c63b91a5c554d743d275a31e17c8e1bc8362430d62c5f0bebd7715ddb4` |
| scientific population | `/Users/jerryyu/Projects/pt1-population-manifest-76508ec-r7.json` | `e7fe84dd2fcf79555c429b9950a3e2dc80b103db1701d804b82f1c218c73ec1c` |
| process-wave receipt | `/Users/jerryyu/Projects/pt1-rehearsal-76508ec-r7.json` | `60418974229ba6fcd1cb6b5ccf131d116baa8e442b625d537255059821a3e002` |
| freeze | `/Users/jerryyu/Projects/pt1-freeze-76508ec-r7.json` | `d05070d755d12f1a7c9a67471599377e0e590ed100f6beb315f7d8ccd915bc90` |
| expected marker | `/Users/jerryyu/Projects/pt1-review-marker-76508ec-r7.json` | `cb3e4667961b065412bf4c6586767aaeb66445b358c70b6d66254e2ff1ae38b7` |
| exact launcher | `/Users/jerryyu/Projects/launch-pt1-76508ec-r7.sh` | `061acb97850f9727d4721ea5bf6402f63ada36f5105134e7f23a6f1d882222f6` |

The capacity packet completed all 416 cells with 10 workers in
`665984859167` wall nanoseconds and `6169311405000` aggregate CPU
nanoseconds. It retained no action, score, point, hidden-world or raw-seed
bytes. The freeze copies the mechanically derived caps without manual edits:

- wall `2320480286303` ns;
- CPU `7711639256250` ns;
- aggregate peak-RSS accounting `10949836800` bytes;
- artifact bytes `9357920`;
- total exact nodes `66846000`;
- exact nodes/state `160688`.

The fresh scientific manifest binds 416/416 distinct cells under commitment
`c7c0ae4953e7fc3c378d573d388728b8bcc5012e2b14360fc2004f02f1fbf942`.
The separate required process-wave receipt exercised 10 real workers / 40
records in 20.0 seconds and persisted no scores or actions. Freeze schema is
`privileged-teacher-pt1-freeze-v3`, deadline equals the derived wall cap,
resume is allowed, runtime/native/boot identities match the completed packet,
and the destination `/Users/jerryyu/Projects/shengji-pt1-evidence-76508ec-r7`
is absent.

Review the actor-visible eligibility predicate, its one-candidate and
tractor-lock witnesses, the worker-failure wiring/redaction, full-grid cap
derivation, population binding, process-wave receipt and exact freeze/marker
reconstruction, plus the exact launcher. The launcher takes only the authentic
review commit, rechecks source/input hashes and the absent destination, fetches
canonical main before execution and again before verification, then invokes
the reviewed run and verify routes without overriding the deadline. If every
boundary passes, append the exact marker at column 1 and authorize one
initialization, execution/resume as frozen, and terminal verification of r7.
Nothing is initialized and no scientific result has run. No merge, retry
outside the frozen resume contract, gameplay, training, strength, promotion or
deployment authority follows.

## Live R4 — monitor only, do not touch

- Host/unit: `shengji-cloud` /
  `belief-r4-completion-e10cb3d-r3.service`.
- Exact source: `e10cb3d3426d758f2d757d41462aba6a06bc60c8`.
- Evidence root: `/opt/belief-r4-completion-v1-r3`.
- Last read-only check: service active/running, `NRestarts=0`, calibration
  partition 1/4 (25%), no terminal/failure/result file and test still unopened.
- Memory current/peak: about 19.3/20.7 GB, below the frozen 24-GiB boundary.

R4 remains the first scientific verdict. PT1 preparation/review may proceed on
Mini without changing R4.

## R5 — held

Do not launch or request another R5 review until R4 is terminally interpreted
and PT1 has progressed. Preserve the isolated R5 successor work and evidence;
there is no active R5 review ask.
