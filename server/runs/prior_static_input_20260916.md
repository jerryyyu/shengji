# Prior static-input qualification — September 16

PR #463, stacked on joint NumPy serving #455. No deployment or gameplay-strength
claim. Source change removes unused history construction before prior inference;
the opening fallback and model weights are unchanged.

## Actual joint-model consumer

Reproducer: `server/scripts/benchmark_prior_static_input.py PACKAGE --full-play`.
Use `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=server`.
JS-M1 package SHA256:
`0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747`.
Factory configuration: W32/N30/R300, static value encoding, successor reuse,
joint prior threshold 1000/top256, seed13. Synthetic heuristic deal seed41,
four plies, 6,940 exhaustive legal actions. No holdout data used.

ABBA within one process, same state and fresh seeded bot each pass; model loading
outside timed decision. Local Mac also running training: NOT isolated fleet
capacity evidence. Alarm bounds each pass at 300 seconds.

| Pass | Whole play (s) | Ranking (s) | Prior stage (s) |
|---|---:|---:|---:|
| Reference | 1.617968 | 0.490098 | 0.020810 |
| Static | 1.531199 | 0.471562 | 0.017518 |
| Static | 1.544159 | 0.492079 | 0.017670 |
| Reference | 1.534165 | 0.479191 | 0.020627 |

All passes activated prior admission and returned identical final actions,
shortlist diagnostic scores/candidates (excluding wall clocks), and RNG state.
The prior-stage saving is about 3 ms here. Whole-decision ranges overlap; do not
promote this to an established end-to-end speedup. The earlier 2.2–3.1x result
was input construction only, not policy throughput.

Second fixture, `--seed 65 --full-play`, otherwise unchanged: 1,064 actions,
prior triggered, all four decision/score/RNG comparisons exact.

| Pass | Whole play (s) | Ranking (s) | Prior stage (s) |
|---|---:|---:|---:|
| Reference | 1.480342 | 0.395838 | 0.008267 |
| Static | 1.436232 | 0.396901 | 0.005845 |
| Static | 1.452304 | 0.410915 | 0.005824 |
| Reference | 1.442926 | 0.399270 | 0.007799 |

Again the whole-decision ranges overlap. This supports an inexpensive local
encoding improvement, not a claim that it resolves serving/search latency.

Tests also cover complete rounds/all seats, opening/follow/terminal states,
hidden-hand/kitty swaps, and joint-NumPy admitted-pool equality. This does not
qualify training changes, PUCT tree changes, or different numerical backends.
