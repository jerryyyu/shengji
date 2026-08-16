# Active Claude/Codex handoff

> Current queue only. Historical reviews belong in `HANDOFF_REVIEW.md` and Git
> history. A request not listed here is not active.

Last reconciled: 2026-08-16 17:12 EDT.

## Immediate objective

Repair the one pre-consumption provenance refusal found after the approved V2
freeze, rebuild the source-bound host packet, obtain one final exact-freeze
PASS, then run the complete outcome-blind DAG without intermediate reviews.

## Top/only Claude ask — PR #119 exact source head `15cc8f8`

Review exact PR #119 head
`15cc8f8` against parent
`d57770b`. This is one narrow source/re-entry review. Do not initialize an
evidence namespace, run capture/reference/training, open calibration/test,
merge, deploy, or grant gameplay/strength authority.

### Incident boundary

The exact-freeze PASS at canonical commit `dda0858` was authentic, but the
first `initialize` call refused before admission construction with:

`BeliefV2FreezeError: V2 execution review marker introduction drift`

The cause is exact: `authenticate_execution_review` required the canonical
ledger's prior population of `BELIEF_V1_V2_OFFLINE_EXECUTION_V1_REVIEW`
markers to be empty. That was valid only for the first V2 freeze. The spent
`13d` authorization is append-only in the ledger, so a legitimate second
fresh marker could never authenticate. After the refusal, the proposed root,
`.partial`, and `.consumed.json` remained absent; no admission or scientific
namespace was consumed and no run stage started.

### Exact repair and checks

- Scope: two files, `+26/-3`:
  `server/shengji/rl/belief_v2_freeze.py` and
  `server/tests/test_belief_v2_freeze.py`.
- The validator now requires the current marker sequence to equal the complete
  prior marker sequence plus exactly one newly appended expected marker.
- It separately refuses when the expected marker already exists in the parent,
  so the same freeze cannot be authorized twice.
- The regression constructs a real parent ledger containing a distinct spent
  freeze marker, appends one marker for a fresh evidence root/freeze, pushes a
  real temporary bare remote, and drives `authenticate_execution_review`.
- Reverting only the repaired condition to the old first-marker rule makes the
  named regression fail with the exact production refusal.
- Focused: `18 passed`.
- Full BELIEF pure: `385 passed, 2 skipped`.
- Full BELIEF compiled strict-void: `387 passed`.
- `git diff --check`: PASS; branch clean and pushed.

Return one consolidated `PASS` or `HOLD` with every blocker found. On PASS,
append the source/re-entry verdict to `HANDOFF_REVIEW.md` in one authenticated
Claude-authored canonical-main commit and name exact head `15cc8f8`.
A PASS authorizes only fresh score-free host measurements and construction of
one new immutable freeze. It is not execution authority.

## Codex work in parallel

Codex completed the clean checkout/runtime and both fresh score-free receipts:

- all-rank preflight SHA `725983a2c012d20635e4dfba61e62c7ffd0d85294c626eff30e81ad5c84ea1de`:
  416/416 rounds, 16 lanes, all 13 ranks, zero stderr;
- deadline receipt SHA `2144d83765c17d42ded2c3fad44df7a5072d47da152e9b118cbad1cac7ccc0cc`:
  416 capture, 32 REF-C, two training samples, CPU, zero stderr, no test or
  result bytes.

The source PASS is the only remaining freeze-construction input. Immediately
after it lands, Codex will freeze one new evidence root and replace this queue
with the exact single freeze-review request. There are no per-stage review
requests after that PASS; the next review will be the terminal independent
reopen.

## Operational truth

- Performance Cloud is on and otherwise idle.
- No V2 population process is running.
- Fresh `d577` evidence root/tombstone were never created.
- The spent `13d` namespace and its old ops logs remain preserved byte-for-byte.
- PR #119 remains draft; merge is not part of this request.
