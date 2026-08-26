# Active Claude/Codex handoff

> Current operational truth and exact review asks only. Historical evidence
> belongs in `HANDOFF_REVIEW.md` and Git history. Do not repeat a superseded
> review. There is exactly one active review ask below.

Last reconciled: 2026-08-25 22:23 EDT.

## Immediate objective

1. Leave the live R4 completion run untouched through calibration, one held-out
   test opening, terminal verification, and independent interpretation.
2. Review only the PT1 `r6b` operator-wrapper correction below; on PASS, Codex
   uses Jerry's standing GO to launch the one authorized Mini execution.
3. Keep R5 held until R4 is terminally interpreted and a final fresh Perf
   packet binds that result. R4 and R5 share one population and are not
   independent replications.

## Live execution — R4 completion-only

R4 requires no further source/freeze review and is active on Strength Cloud
under the exact `e10cb3d/r3` PASS marker in ledger commit `68e4522f`.

- unit: `belief-r4-completion-e10cb3d-r3.service`
- source: `e10cb3d3426d758f2d757d41462aba6a06bc60c8`
- freeze SHA-256:
  `59c747be56bdd20c792608ed09be307b9661c8aff6ad7e0e720cd8156de7fea4`
- evidence: `/opt/belief-r4-completion-v1-r3`
- phase: calibration, 1/4 outer stages, test unopened
- last direct health check, 2026-08-26 02:17 UTC: active/running,
  `NRestarts=0`; worker using about 13.5 of 16 CPUs; cgroup peak
  `20,366,786,560` bytes below the 24 GiB cap

Do not modify, restart, delete, merge, or infer a result from the outer 25%
counter. It advances only after the whole calibration stage publishes.

## Review queue — exactly one operator-wrapper review

### PT1 `r6b`: correct the launcher's stale repository URL

The exact PT1 source+freeze review already PASSed at source
`e27240e46981cae9db099236113a2b655d88570c`; its expected marker occurs exactly
once in canonical ledger commit
`31cca4d18bd1c2254f2dfbec9fd8a639cb265ee5`. Do **not** reopen source,
design/search/statistics, population, capacity, rehearsal, freeze, secret, or
scientific-marker surfaces.

The reviewed `r6` operator launcher was then invoked once and refused before
initialization because its shell-only `git ls-remote` precheck still used the
nonexistent two-`y` owner `jerryyu`. The repaired production code correctly uses
the real three-`y` owner `jerryyyu`, but the independently generated shell
wrapper had not inherited that repair.

Measured refusal boundaries:

- old launcher:
  `/private/tmp/pt1-launch-operator-e27240e-r6.sh`
  - SHA-256
    `7974bf9064358ffac8bc7a8d86fda146b614de523b5676ec1159fb3955f1b0a4`
- old status SHA-256:
  `2051c3429aae403120271a5763d58ff95b31e71f93c77423ff123e16236dafbb`
  - phase `failed`, completed `0/3`
- old log SHA-256:
  `ae16b2fc7a313579dacbf6d4ca21b1105b2bb0f4997e4b0ca7035be5dd848953`
  - exact refusal is `Repository not found` for
    `https://github.com/jerryyu/shengji.git`
- evidence root
  `/Users/jerryyu/Projects/shengji-pt1-evidence-e27240e-r6` is absent
- no initialize/run/verify command ran; no scientific secret, state, score, or
  action byte was opened; the authorized scientific slot remains unconsumed

Review the new launcher only:

- `/private/tmp/pt1-launch-operator-e27240e-r6b.sh`
- SHA-256
  `ca7743de78a65c9599eee8aae0b0e1c245f44eb6178598f47e683856bc5c9fef`
- mode `0500`, link count 1, owner is the current Mini user
- `zsh -n` passes
- `git ls-remote https://github.com/jerryyyu/shengji.git refs/heads/main`
  succeeds at canonical main; the old two-`y` URL refuses
- fresh `r6b` status and log slots are absent

The diff from the already-reviewed launcher is exactly three lines:

1. change the shell precheck from `jerryyu` to the correct `jerryyyu`;
2. move only the operator status path from suffix `r6` to `r6b`;
3. move only the operator log path from suffix `r6` to `r6b`.

All execution inputs remain byte-identical: source `e27240e`, freeze
`64352206b3e930eefa431c3b358356915bd5cb65708d0056c7711b7ef367d8dc`,
marker `14abd7e247c137f3869761375959412ffd79e3d9009ec08470acf4b4030d5502`,
population `dfa50966aa7b846a9b072a3585403249c15b80fa8026f2e277cfe644ca1ae87c`,
scientific-secret commitment, native binary, ten workers, caps, deadline, and
evidence root.

If the exact three-line operator delta and the pre-initialization refusal
boundaries verify, append one concise `r6b` operator-launcher PASS entry bound
to both launcher hashes, source `e27240e`, freeze SHA, canonical scientific
marker commit `31cca4d`, and the absent evidence root. No new scientific marker
is needed. Then Codex launches `r6b` once under the existing authority and
standing GO. No merge, retry, training, gameplay, strength, promotion, or
deployment authority follows.

## Held — not an active review

PR #148 at exact head `7e14b529065383baee152c9dd2b8d3473627235c`
is source/CI green. Its old Perf freeze is boot-bound and must not be reused
after the host power cycle. After R4 terminal interpretation, Codex will build
one fresh final R5 packet binding the R4 result and request one consolidated
source+freeze review. Performance Cloud is offline and is not currently needed.

## Fleet

| host | current state | next action |
|---|---|---|
| Strength Cloud | R4 completion active in calibration | monitor only; interpret terminal result |
| Mini | idle after pre-init PT1 wrapper refusal | launch `r6b` once after the exact operator PASS |
| Performance Cloud | offline; no R5 job | hold until R4 interpretation |
| Air | idle / not required | none |

## Authority boundaries

No active packet authorizes merge, retry, deployment, promotion, gameplay, or
a strength claim. R4 is already running once under its exact marker. PT1 has
one unconsumed scientific execution authority, but the corrected operator
wrapper must PASS before use. R5 remains held.
