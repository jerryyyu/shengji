# Joint-model successor prediction reuse: local qualification

Opt-in integrated factory path, based on PR463 ae938359; no production defaults
changed. JS-M1 package SHA256
`0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747`.
Compiled engine, single-thread BLAS, W32/N30/R300, prior threshold1000/top256,
bot seed13. Synthetic heuristic deals, not held-out gameplay. Shared Mac with
peer training: these timings are exploratory, not isolated fleet throughput.

Reproduce with `server/scripts/benchmark_value_reuse.py PACKAGE` under
`SHENGJI_FAST=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=server`.
ABBA order means off/on/on/off; each decision has a 300s process alarm.

| Seed / plies | Legal actions | Off wall seconds (two) | On wall seconds (two) | Requested / forwarded value rows |
|---|---:|---|---|---:|
| 41 / 4 | 6940 | .661026 / .632554 | .440834 / .416653 | 17536 / 837 |
| 65 / 4 | 1064 | .534493 / .569861 | .368884 / .385694 | 14016 / 835 |
| 19 / 5 | 3 | .178974 / .181659 | .189153 / .184999 | 96 / 96 |
| 3 / 24 | 89 | .262819 / .264128 | .251669 / .246823 | 2848 / 542 |
| 19 / 48 | 23 | .145547 / .145271 | .154062 / .143607 | 736 / 482 |
| 3 / 64 | 15 | .102048 / .089496 | .087841 / .086483 | 480 / 186 |

All 24 decisions preserved selected action and final RNG state. Maximum
shortlisted-mean difference was 1.11e-16 (seed65); others were zero. This does
not prove byte identity of raw network outputs: changing inference batch
shapes can change floating-point rounding and near-tie decisions elsewhere.
The earlier raw-output diagnostic observed differences up to 1.44e-15.

The two wide cases reduced mean full-decision wall by approximately 34% and
32%. The small follow with no duplicate successors showed no benefit and a
small measured slowdown; do not claim universal gains. Persistent retained
cache entries never exceeded128; this is an object bound, not a measured RSS
bound. More numerical coverage and isolated runtime/memory qualification
remain before enabling the option in serving or data generation.

Focused cache/identity/registry tests: 37 passed. Historical recipe digests
remain unchanged when reuse is disabled; enabling reuse gives a new identity.
