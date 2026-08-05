# Active Claude/Codex handoff

Last decision: 2026-08-05 09:00 EDT. Read this file before the append-only
discussion in `HANDOFF_REVIEW.md`. This is the operational front door; keep it
short and replace stale status instead of appending a second answer.

## The decision that unblocks the work

The sampler question had two different estimands mixed together:

1. **Correctness estimand:** does the sampler draw the true physical-deal
   posterior? No. P0 validity/support passed, but posterior weighting is not
   certified. Weighted splits are slow and still biased, so all three
   experimental sampler flags remain OFF.
2. **Strength-screen estimand:** which ballot/search design makes the strongest
   decisions when paired with the exact MC sampler deployed today? The DEV
   pilot may answer this. Freeze the current sampler as part of the policy,
   compare every arm under it, and require CALIB plus full-game online
   confirmation before promotion.

Therefore do **not** describe the bias as harmless or the sampler as correct,
but do **not** block the DEV strength screen on an exact-posterior research
project. If the sampler changes later, the winning ballot must be revalidated.
Do not run another enumerable-state posterior or decision-sensitivity job now.

## Current state

- Experiment code is based on `0f65dbf`; Claude's sampler diagnostics and
  documentation are dirty. A later Codex docs-only commit may sit above it.
- DEV/CALIB v3 files are tracked and their current bytes replay correctly, but
  the registered freeze mechanism is not closed: candidate-size allocation was
  not predeclared identically, shortage can write a short artifact, and the
  tests do not exercise those failures.
- The lead pilot has scored 0/512 states. The fleet is idle.
- `pilot_run.py` still defaults to nonexistent `pilot_states.v4.json` and does
  not fail closed against the registered artifact hash or sampler flags.

## Claude work package A — close the freeze gate (do this now; 60–90 min)

Predeclare and implement these identical DEV/CALIB band-size marginals. They
are the rounded pooled midpoint of the already-visible v3 metadata; no action
values or outcomes have been inspected:

| trick band | small | med | wide | total |
|---|---:|---:|---:|---:|
| early | 0 | 72 | 98 | 170 |
| mid | 11 | 131 | 29 | 171 |
| late | 152 | 19 | 0 | 171 |

Role marginals remain attacker/defender 85/85 in early and 86/85 in each of
mid and late. Size and role are exact band-level marginals; do not invent
post-hoc role-by-size targets. Selection must choose a deal that fills a live
size deficit, not pick a deal first and merely choose among that deal's rows.

Acceptance criteria, all mandatory:

0. First finish the current dirty diagnostic block: reconcile `JOBS.md` to the
   recorded 540,000-attempt result and item-0 status, revise `AI_POLICIES.md`
   to separate posterior correctness from the frozen-production strength
   estimand, verify all flags default OFF, then commit and push. Do not carry a
   dirty measurement tree into the freezer work.
1. `--n` must equal 512; any other value is refused because the quotas are a
   512-state contract.
2. Before writing, assert exactly 512 picks, exact band/size and band/role
   marginals, 512 unique deals, the requested DEV or CALIB split, no REPORT
   membership, zero replay errors, and current source **and split** digests.
3. Any shortage, replay error, mismatch, dirty tree, or existing output path
   exits nonzero and leaves no final artifact. Do not merely record the defect.
4. Tests must execute a synthetic shortage and replay-error path and prove no
   artifact is published. Replace the vacuous `state.get("split")` REPORT check
   with membership checks against the declared split files. Replay all 1,024
   frozen states in the certification test or a dedicated validator, not six.
5. Commit and push the freezer/test change first. From that clean commit freeze
   new-salt `pilot_dev512.v4.json` and `pilot_calib512.v4.json`, force-add them,
   register full hashes, and commit/push the artifacts. Do not edit v1–v3.

If the exact quotas are infeasible, stop within 30 minutes and report the
available `(band, size, role, split)` matrix plus the first unsatisfied cell.
Do not silently relax or choose replacement quotas.

## Claude work package B — make the score runner launch-safe (30–60 min)

Start only after v4 hashes exist. Make the smallest patch that closes these
specific holes:

1. Remove the nonexistent v4 default: require an explicit `--states` and
   `--expected-states-sha256`, compare the full digest before corpus loading,
   and record both in every shard.
2. For a full run, refuse anything except 512 selected states, the DEV side,
   exact registered marginals, unique deals, and zero replay errors. A limited
   smoke must be labelled `smoke` in the manifest so it cannot aggregate as a
   full DEV result.
3. Refuse if `SHENGJI_WEIGHTED_SPLITS`, `SHENGJI_UNIFORM_DEAL`, or
   `SHENGJI_PHYSICAL_FILLS` is set. Require compiled mode and strict voids as
   today. Record the three flags as false in the manifest.
4. Add runner-preflight tests for wrong hash, wrong side/count, an enabled
   sampler flag, and a smoke masquerading as a full run. Add `phase` and flag
   identity to the aggregator's cross-shard equality checks.

Before the runner commit, run from `server/`:

```text
uv run pytest -q tests/test_pilot_freezer.py tests/test_pilot_arms.py tests/test_pilot_folds.py tests/test_pilot_score.py tests/test_pilot_aggregate.py tests/test_banker_sampler.py tests/test_sampler_constraints.py tests/test_sampler_voids.py
SHENGJI_FAST=1 uv run pytest -q tests/test_pilot_freezer.py tests/test_pilot_arms.py tests/test_pilot_folds.py tests/test_pilot_score.py tests/test_pilot_aggregate.py tests/test_banker_sampler.py tests/test_sampler_constraints.py tests/test_sampler_voids.py
```

Also require `git diff --check`, all sampler flags false by default, a clean
tree, and a pushed commit. Land the current dirty diagnostics separately first;
do not mix measurement artifacts and the launch-runner patch in one commit.

## Gate review packet — return this, not another narrative

Claude should post exactly:

```text
STATE: READY_FOR_CODEX_GATE | BLOCKED
HEAD / origin HEAD:
dirty files:
v4 DEV hash / CALIB hash:
quota + role + replay + split + disjoint audit:
pure tests / compiled tests:
two identical smoke hashes:
sampler flags:
exact fleet command:
if BLOCKED: failing command, first error, recommended fix, ETA
```

Codex will answer `PASS` or list numbered defects. Do not start a new research
branch while waiting for that review.

## After PASS — launch DEV-512, not CALIB

Use eight state-strided shards from one clean pushed commit: Mini indices 0–3,
Air 4–7, one process per shard. Before launch, both machines must report the
same HEAD, DEV artifact hash, ballot identity, and Mini-built compiled binary
identity; do not rebuild the extension on Air. The command must retain the
registered values: budget 14, equal work 168 +/-5%, 12 full-proposal worlds,
12 oracle worlds, 12 report worlds, one salt, and no `--limit`.

Monitor only liveness, completeness, hashes, counters, and protocol failures.
Do not inspect arm outcomes or extend the sample while shards are running. Stop
on any short fold, rejected/impossible/zero-world counter, replay error, work
violation, mixed identity, or missing state. After all eight complete, aggregate
once. The result may select exactly one complete design or select none.

## Handoff protocol from now on

- `HANDOFF_ACTIVE.md`: one current decision, one active package, one gate
  packet. Target under 200 lines.
- `HANDOFF_REVIEW.md`: append-only evidence and disagreements; never the place
  someone must search to discover today's command.
- `JOBS.md`: facts from live processes/artifacts only. Check processes before
  writing RUNNING.
- `BACKLOG.md`: product sequence and gates in plain English, not run chatter.
- Every claim is marked `CONFIRMED`, `PROVISIONAL`, `SCREEN`, or `WITHDRAWN`.
- A diagnostic gets a written question, decision threshold, and timebox before
  code or compute. At the timebox, recommend one path; do not leave three
  uncosted options for the next reviewer.
