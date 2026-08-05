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

## Deep-lead reservoir and the 512 evaluation sets (2026-08-05)

| artifact | sha256 | status |
|---|---|---|
| `deep_leads.v1.jsonl` | `ffccfde64932eb3a` | **FROZEN** — 768 rows, 48 cells x 16 |
| `deep_lead_split.v1.json` | `9d72dcafffc1d8ac` | **IMMUTABLE** |
| `pilot_dev512.v1.json` | `178d9efa615dd589` | SUPERSEDED — role balance was a no-op |
| `pilot_calib512.v1.json` | `bc87dd50ae79f6d2` | SUPERSEDED — same defect |
| `pilot_dev512.v2.json` | `d167d1f140f88d68` | PROVISIONAL — structural audit passes; freeze contract does not |
| `pilot_calib512.v2.json` | `90c00af09ae084b7` | PROVISIONAL — structural audit passes; freeze contract does not |

v1 of each is superseded because `roles_by_band` reported `?` for every band:
selected rows never carried a `role`, so the balancing loop found no matching
options and fell through to its "take any remaining deal" fallback on every
iteration. The composition was right by luck of the draw; the mechanism was not
running. v1 files are left byte-unchanged.

Both v2 sets were generated from a clean tree at ballot `a68f7b8bced6` and
independently replay clean: 512 states, 512 unique deal seeds, bands
170/171/171, roles 85/85 + 86/85 + 86/85 per band, ZERO deal overlap between
DEV and CALIB, and no REPORT row selected in either.

They are **not promotion-grade frozen artifacts**. `pilot_states.py` alternates
roles, but merely reports candidate-size strata after selection; it never uses
candidate size to select a row, contrary to the preregistration. It can also
write fewer than the requested quota without failing, and has no contract test
for the frozen-set invariants. Finally, all four DEV/CALIB JSON files are under
the repository-wide `rl_data/` ignore rule and are not tracked by git, so a
fresh clone contains only these hashes, not the purported artifacts. Keep v2
byte-unchanged and supersede it with new-salt v3 outputs only after those
issues are fixed and tested.

**These are evaluation artifacts, not training corpora.** REPORT's 256
reservoir rows have not been selected or scored.

## v3 — the gate artifacts (2026-08-05)

| artifact | sha256 | status |
|---|---|---|
| `pilot_dev512.v3.json` | `d8d5d04abb9f9262` | **DEV-512 GATE SET** |
| `pilot_calib512.v3.json` | `5e4c9a8d4a6310ac` | **CALIB-512 GATE SET** |
| `pilot_dev512.v2.json` | `d167d1f140f88d68` | superseded — no candidate-size balance |
| `pilot_calib512.v2.json` | `90c00af09ae084b7` | superseded — same |

v3 closes the five freezer defects Codex listed: the deep reservoir is in
`SOURCES`, `--side` selects DEV or CALIB (never REPORT), the registered quota
170/171/171 is enforced rather than emergent, role balance is enforced per band
(85/85, 86/85, 86/85 on both sets), and candidate-size stratum is now a
secondary selection key rather than a recorded-but-ignored field.

`tests/test_pilot_freezer.py` is the committed contract: sources, quotas,
one-state-per-deal, role balance, DEV/CALIB deal-disjointness, source/split
digest currency, dirty-tree and existing-path refusal, and replay of sampled
states. 10 cases.

**On candidate size:** balance is enforced WITHIN what each band can supply,
not across bands. Late-trick states have small hands and therefore small
ballots (`late` is 151 small / 20 med); early states have large ones (`early`
is 98 wide / 72 med). That is the game, not a selection failure, and it is
recorded per band so an analysis can condition on it.

Both sets frozen from a clean tree at ballot `a68f7b8bced6`. Deal-disjoint,
zero REPORT rows. REPORT's 256 reservoir rows remain unread.
