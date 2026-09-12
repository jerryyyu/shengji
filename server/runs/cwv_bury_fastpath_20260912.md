# Bury fast-path investigation — 2026-09-12

Unpublished implementation candidate: enable the existing trusted-rollout
engine path in `_rollout_from_bury` for exact built-in `HeuristicBot` only.
Custom/subclass continuations retain full validation. Lead/throw validation
remains active. No production deployment, budget or recipe change.

A second candidate validates each model-ranking world once, rather than once
per burial. The direct `post_bury_world` entry still fully validates. Batch
templates are immutable and each candidate receives fresh hand lists.

## Correctness so far

The trusted-rollout change passed 26 tests in each engine mode. After adding
validation reuse, the expanded suite passes 32 tests in each engine mode. New tests
compare every requested/accepted play, score, turn and trick winner across six
natural deals and two burial candidates each. They prove redundant follow
validation is removed, lead validation remains, root state/RNG are unchanged,
and the actual hybrid wrapper preserves shortlist/model/MC evidence and pick.
Additional tests verify exactly one population validation per world, reject
an invalid later world, and prove an evaluator that mutates its received hands
cannot poison a later candidate or the original world.

## Measurements and an important correction

All measurements below were on a **contended Mini**, not an isolated Fly host.
The first cProfile run did not activate native acceleration: 2.155 seconds,
0.705 model phase and 1.446 rollout phase. This is NOT a production latency
estimate and must not determine native optimization priorities.

Explicit `fast.activate()` changes the picture. Using deployed compact model
`fd6bb4114eb1f2ff049a77989cbd99eb35b949eef944dd72de448ff25b4fabd9`,
hybrid C32/W32/N32/K4 and seed 123 on natural fixture deals 7/13/31:

| Deal | Reference wall, two passes | Trusted wall, two passes |
|---|---|---|
| 7 | 0.207 / 0.261 s | 0.180 / 0.180 s |
| 13 | 0.315 / 0.340 s | 0.321 / 0.304 s |
| 31 | 0.242 / 0.287 s | 0.247 / 0.280 s |

Order was reference/trusted/trusted/reference per deal. Reference disables
only the new flag in the same method; it retains the same built-in policy and
native engine. Every pass exactly matched choices, RNG, model means, MC
evidence, worlds and counters. These noisy samples do not establish a speedup.
Serving deadlines were disabled to measure completed work; timing-dependent
fallback behavior under the two-second serving budget remains to qualify.

The combined candidate was also compared to the pre-change code from commit
`82313b30` on these three deals, again old/new/new/old. All 12 completed calls
matched the exact evidence above. Contended wall ranges were 0.240–0.353 s old
and 0.213–0.304 s new; the overlap is substantial and this remains parity
evidence, not a qualified timing claim.

Native cProfile on deal 7 with the candidate took 0.329 seconds:

- model candidate phase: 0.255 s;
- static encoding: 0.124 s for 832 positions;
- NumPy probability forward: 0.053 s, including 0.043 s in exact GELU;
- full rollout phase: 0.054 s;
- repeated world validation: 0.035 s.

Profile overhead is included; these are overlapping cumulative times, not
additive independent buckets. Native ranking is the larger target. Next
investigate repeated per-world validation and static encoding reuse; exact
GELU's Python vectorization is another candidate, but replacements must retain
prediction bytes rather than silently adopting an approximate activation.

Before adoption: isolated timing/resources on representative natural deals,
actual NumPy/Torch consumer parity as applicable, serving-boundary tests and
one source review. Keep live source/output trees unchanged.

## Isolated native NumPy qualification

Completed on Perf, artifact root `/root/bury-cost.o3EZnP`. Exact deployed
compact model above; both source trees use the same verified native extension.
The reference tree is commit `82313b30`; candidate changes only the two bury
paths. `server/scripts/cwv_bury_cost.py` records the actual source-file hashes.
Three natural deals, three repeats each, reference/candidate/candidate/reference
process order; model warmup excluded, completed-work deadlines disabled.

All 36 calls agree on semantic hashes covering final choice, RNG, candidates,
shortlist, model means, MC evidence and sampling counters.

| 18 calls per arm | Reference | Candidate |
|---|---:|---:|
| Wall | 5.8367 s | 5.1570 s |
| CPU | 5.8363 s | 5.1567 s |
| Model phase | 4.1976 s | 3.9293 s |
| Rollout phase | 1.6094 s | 1.1971 s |
| Process peak RSS | 62.6–62.7 MB | 62.6 MB |

Observed wall reduction 11.6% (1.132x throughput), not a Fly p95 or a general
all-rank forecast. The queue/controller and 17 children were paused for 13.62s;
all 19 captured process identities were resumed in `finally`, and the parent
was verified running afterward. Live sources and outputs were untouched.
