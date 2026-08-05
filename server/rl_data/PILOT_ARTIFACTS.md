# Pilot artifact ledger

Supersession is recorded HERE, never inside a frozen artifact. Editing a frozen
file to mark it superseded — which is what happened to v1 and v2 on 08-05 while
the commit message said "kept unedited" — destroys the immutability the freeze
exists to provide (Codex). Both have since been restored to their original
bytes.

| artifact | sha256 | status | why |
|---|---|---|---|
| `pilot_states.v1.json` | `717091bd15b7` | SUPERSEDED | written from a DIRTY tree; stale ballot digest `0c5647302082`; strata computed AFTER selection popped rows, so they described the residual pool |
| `pilot_states.v2.json` | `3c60d73e3f13` | SUPERSEDED | the generator marked a deal seen at its FIRST eligible row, so later lead states from that deal never competed: 229 early / 281 mid / **2 late** under the trick index |
| `pilot_states.v3.json` | current | **DEV ENGINEERING SET ONLY** | deal-grouped and banded, clean tree, ballot `a68f7b8bced6`. NOT a gate set: 255/254/**3** by trick band and 199/313 attacker/defender is not the balanced broad-lead gate BALLOT_PLAN specifies |

The Gate 2 runner contract was smoke-verified twice on the first eight v3
states at clean commit `8ee2d93`; both complete JSON files had SHA-256
`a926cbb013fb54188a81017394b87bf23d78f8486173603c9165fe772b3f46f1`
and passed aggregation. This is protocol evidence only, not an artifact or a
strength result. The next immutable rows will be registered here only after
the deep reservoir's merge succeeds.

## What v3 is and is not

Only **3 DEV deals** contain any lead state at trick index >= 12 (early 3118 /
mid 1495 / late 3). That is a supply limit in the corpus, not a selection bug —
the late supplement's depth is in PLIES and most of its deep rows are follows.

Per Codex, the resolution is option **(b)**: predeclare and capture deep LEAD
states as a new job, then freeze DISTINCT DEV and CALIB artifacts. Stratifying
on something else instead would change the estimand; running v3 as the gate
would overstate scope.

**The gate set must come from CALIB.** v3 is DEV. Gating on it would tune the
arms on the set that judges them.
