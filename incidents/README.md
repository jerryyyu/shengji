# Incidents

Postmortems for correctness and operational failures. One file per
incident, newest first. `CORRECTNESS.md` keeps the one-line index and
the rules these incidents produced; this folder keeps the reasoning.

**Severity levels**
- **S1 data-corrupting** — wrong data entered (or nearly entered) a
  training set or a published measurement
- **S2 measurement-invalidating** — a number we acted on was wrong
- **S3 wasted-compute** — no bad data, but capacity burned
- **S4 near-miss** — caught before impact; recorded because the next one
  might not be

| id | date | severity | title | detected by |
|---|---|---|---|---|
| [INC-12](INC-20260812-12-fleet-monitor-false-negative.md) | 08-12 | S3 | Wrong process filter reported Air idle and triggered a duplicate S6 census | exact process/namespace reconciliation |
| [INC-11](INC-20260803-11-fast-path-noop.md) | 08-03 | S4 | `SHENGJI_FAST=1` was a no-op outside pytest | validation agent |
| [INC-10](INC-20260803-10-orphaned-workers.md) | 08-03 | S1 | Orphaned workers wrote buggy-code data for 10h | process-age audit |
| [INC-09](INC-20260803-09-throw-penalty-rule.md) | 08-03 | S2 | Failed throws forfeited the first, not lowest, beatable component | Jerry, from play |
| [INC-08](INC-20260803-08-cython-drift.md) | 08-03 | S4 | Cython port implemented pre-audit memo semantics | contract tests |
| [INC-07](INC-20260803-07-cache-key-mismatch.md) | 08-03 | S1 | Memo keys didn't capture order-dependent computation | audit agent |
| [INC-06](INC-20260802-06-determinism.md) | 08-02 | S2 | Hash-ordered iteration made "fixed seeds" irreproducible | golden tests |
| [INC-05](INC-20260802-05-cache-alias.md) | 08-02 | S1 | Memo returned mutable lists a caller mutated | golden tests |
| [INC-04](INC-20260802-04-ballot-leak.md) | 08-02 | S2 | MCBot default flip silently widened RL play-time ballots | Jerry's question |
| [INC-03](INC-20260801-03-elo-798.md) | 08-01 | S2 | Ballot change collapsed the deployed net to Elo 798 | pool anomaly |
